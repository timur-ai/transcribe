"""Task queue service — asyncio-based queue for parallel file processing."""

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field

from telegram import Bot

from src.bot.keyboards import get_pdf_keyboard
from src.db import repository as repo
from src.services.audio import AudioProcessor
from src.services.speechkit import SpeechKitClient
from src.services.storage import ObjectStorageClient
from src.services.yandexgpt import YandexGPTClient

logger = logging.getLogger(__name__)

# Cost per second for deferred mode
SPEECHKIT_COST_PER_SEC = 0.002542


@dataclass
class ProcessingTask:
    """A file processing task in the queue."""
    chat_id: int
    file_path: str
    file_name: str
    message_id: int
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    enqueued_at: float = field(default_factory=time.time)


class TaskQueue:
    """Async task queue with multiple workers for file processing.

    Manages enqueueing, dequeuing, and parallel execution of
    audio/video transcription + analysis tasks.
    """

    def __init__(
        self,
        bot: Bot,
        session_factory,
        audio_processor: AudioProcessor,
        storage_client: ObjectStorageClient,
        speechkit_client: SpeechKitClient,
        yandexgpt_client: YandexGPTClient,
        pdf_generator,
        settings,
        num_workers: int = 3,
    ) -> None:
        self._bot = bot
        self._session_factory = session_factory
        self._audio = audio_processor
        self._storage = storage_client
        self._speechkit = speechkit_client
        self._gpt = yandexgpt_client
        self._pdf = pdf_generator
        self._settings = settings
        self._queue: asyncio.Queue[ProcessingTask] = asyncio.Queue()
        self._num_workers = num_workers
        self._workers: list[asyncio.Task] = []
        self._active_tasks: dict[str, ProcessingTask] = {}

    async def start(self) -> None:
        """Start worker coroutines."""
        for i in range(self._num_workers):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)
        logger.info("Started %d queue workers", self._num_workers)

    async def stop(self) -> None:
        """Gracefully stop all workers."""
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("Stopped all queue workers")

    async def enqueue(self, task: ProcessingTask) -> int:
        """Add a task to the queue. Returns the queue position."""
        await self._queue.put(task)
        position = self._queue.qsize()
        logger.info("Enqueued task %s (position %d)", task.task_id, position)
        return position

    def get_queue_size(self) -> int:
        """Get the current number of tasks in the queue."""
        return self._queue.qsize()

    async def _worker(self, worker_id: int) -> None:
        """Worker coroutine that processes tasks from the queue."""
        logger.info("Worker %d started", worker_id)
        while True:
            try:
                task = await self._queue.get()
                self._active_tasks[task.task_id] = task
                try:
                    await self._process_file(task)
                except Exception as e:
                    logger.exception("Worker %d error processing task %s: %s", worker_id, task.task_id, e)
                    await self._send_message(task.chat_id, f"❌ Ошибка обработки: {e}")
                finally:
                    self._active_tasks.pop(task.task_id, None)
                    self._queue.task_done()
            except asyncio.CancelledError:
                break

    async def _send_message(self, chat_id: int, text: str, **kwargs) -> None:
        """Send a message to the user."""
        try:
            await self._bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as e:
            logger.error("Failed to send message to %d: %s", chat_id, e)

    async def _process_file(self, task: ProcessingTask) -> None:
        """Execute the full processing pipeline for a file."""
        chat_id = task.chat_id
        file_path = task.file_path
        file_name = task.file_name
        start_time = time.time()
        tmp_dir = self._settings.tmp_dir
        os.makedirs(tmp_dir, exist_ok=True)

        ogg_path = None
        remote_keys: list[str] = []
        part_files: list[str] = []

        try:
            # Step 1: Extract audio from video if needed
            if self._audio.is_video(file_path):
                await self._send_message(chat_id, "🔊 Извлекаю аудиодорожку...")
                ogg_path = os.path.join(tmp_dir, f"{task.task_id}_audio.ogg")
                await self._audio.extract_audio(file_path, ogg_path)
            else:
                # Convert to OGG OPUS
                ogg_path = os.path.join(tmp_dir, f"{task.task_id}_converted.ogg")
                await self._audio.convert_to_ogg(file_path, ogg_path)

            # Step 2: Get duration for cost estimation
            duration = await self._audio.get_duration(ogg_path)

            # Step 3: Split if necessary
            parts_dir = os.path.join(tmp_dir, f"{task.task_id}_parts")
            parts = await self._audio.split_file(
                ogg_path,
                parts_dir,
                max_duration=self._settings.max_file_duration_seconds,
                max_size=self._settings.max_file_size_bytes,
            )

            if len(parts) > 1:
                await self._send_message(chat_id, f"✂️ Файл разделён на {len(parts)} частей")
                part_files = parts

            # Step 4: Upload to Object Storage
            await self._send_message(chat_id, "☁️ Загружаю в облако...")
            for part in parts:
                remote_key = f"audio/{task.task_id}/{os.path.basename(part)}"
                self._storage.upload_file(part, remote_key)
                remote_keys.append(remote_key)

            # Step 5: Recognize each part
            all_texts = []
            for i, key in enumerate(remote_keys, 1):
                if len(remote_keys) > 1:
                    await self._send_message(
                        chat_id, f"🎙 Распознаю речь... (часть {i} из {len(remote_keys)})"
                    )
                else:
                    await self._send_message(chat_id, "🎙 Распознаю речь...")

                audio_uri = self._storage.get_storage_uri(key)

                # Start timeout monitor
                timeout_task = asyncio.create_task(
                    self._timeout_monitor(chat_id, duration, start_time)
                )

                try:
                    text = await self._speechkit.recognize(audio_uri)
                    all_texts.append(text)
                finally:
                    timeout_task.cancel()

            transcription_text = " ".join(all_texts)

            # Step 6: Analyze with YandexGPT
            await self._send_message(chat_id, "🤖 Анализирую текст...")
            analysis_text = await self._gpt.analyze(transcription_text)

            # Step 7: Save to DB
            cost = duration * SPEECHKIT_COST_PER_SEC
            file_type = "video" if self._audio.is_video(task.file_path) else "audio"

            async with self._session_factory() as session:
                user = await repo.get_or_create_user(session, chat_id)
                t = await repo.save_transcription(
                    session,
                    user_id=user.id,
                    file_name=file_name,
                    file_type=file_type,
                    duration_seconds=duration,
                    transcription_text=transcription_text,
                    analysis_text=analysis_text,
                    cost_rubles=cost,
                )
                await session.commit()
                transcription_id = t.id

            # Step 8: Send result
            result_text = ""
            if transcription_text:
                truncated = transcription_text[:3500]
                result_text += f"📝 *Транскрибация:*\n{truncated}\n\n"
            if analysis_text:
                truncated_analysis = analysis_text[:3500]
                result_text += f"📊 *Анализ:*\n{truncated_analysis}"

            if not result_text:
                result_text = "⚠️ Не удалось распознать речь в файле."

            keyboard = get_pdf_keyboard(transcription_id)
            await self._send_message(chat_id, result_text, reply_markup=keyboard)
            await self._send_message(chat_id, "✅ Готово!")

            elapsed = time.time() - start_time
            logger.info(
                "Task %s completed in %.1fs (%.1f min audio, cost %.2f ₽)",
                task.task_id, elapsed, duration / 60, cost,
            )

        finally:
            # Cleanup: delete from Object Storage
            for key in remote_keys:
                try:
                    self._storage.delete_file(key)
                except Exception as e:
                    logger.warning("Failed to delete %s: %s", key, e)

            # Cleanup: delete local temp files
            for path in [file_path, ogg_path] + part_files:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

            # Cleanup: parts directory
            parts_dir = os.path.join(tmp_dir, f"{task.task_id}_parts")
            if os.path.isdir(parts_dir):
                try:
                    import shutil
                    shutil.rmtree(parts_dir, ignore_errors=True)
                except Exception:
                    pass

    async def _timeout_monitor(
        self, chat_id: int, duration: float, start_time: float
    ) -> None:
        """Monitor processing time and notify user if it takes too long."""
        # Expected processing time: ~10 sec per 1 min of audio + 5 min buffer
        expected_time = (duration / 60) * 10 + 300  # seconds
        await asyncio.sleep(expected_time)
        elapsed = time.time() - start_time
        await self._send_message(
            chat_id,
            f"⚠️ Обработка занимает больше времени, чем ожидалось "
            f"({elapsed / 60:.0f} мин). Пожалуйста, подождите...",
        )
