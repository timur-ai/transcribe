"""Unit tests for task queue service."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.queue import ProcessingTask, TaskQueue, SPEECHKIT_COST_PER_SEC


@pytest.fixture
def mock_services():
    """Create all mock services needed for TaskQueue."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()

    session = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    session_factory = MagicMock(return_value=cm)

    audio_processor = AsyncMock()
    audio_processor.is_video = MagicMock(return_value=False)
    audio_processor.is_audio = MagicMock(return_value=True)
    audio_processor.convert_to_ogg = AsyncMock()
    audio_processor.extract_audio = AsyncMock()
    audio_processor.get_duration = AsyncMock(return_value=120.0)
    audio_processor.split_file = AsyncMock(return_value=["/tmp/part1.ogg"])

    storage_client = MagicMock()
    storage_client.upload_file = MagicMock()
    storage_client.delete_file = MagicMock()
    storage_client.get_storage_uri = MagicMock(return_value="https://storage.yandexcloud.net/bucket/key")

    speechkit_client = AsyncMock()
    speechkit_client.recognize = AsyncMock(return_value="Распознанный текст")

    yandexgpt_client = AsyncMock()
    yandexgpt_client.analyze = AsyncMock(return_value="## Резюме\nАнализ текста")

    pdf_generator = MagicMock()

    settings = MagicMock()
    settings.tmp_dir = "/tmp/transcribe"
    settings.max_file_duration_seconds = 14400
    settings.max_file_size_bytes = 1073741824

    return {
        "bot": bot,
        "session_factory": session_factory,
        "audio_processor": audio_processor,
        "storage_client": storage_client,
        "speechkit_client": speechkit_client,
        "yandexgpt_client": yandexgpt_client,
        "pdf_generator": pdf_generator,
        "settings": settings,
    }


@pytest.fixture
def task_queue(mock_services):
    """Create a TaskQueue instance with mock services."""
    return TaskQueue(
        bot=mock_services["bot"],
        session_factory=mock_services["session_factory"],
        audio_processor=mock_services["audio_processor"],
        storage_client=mock_services["storage_client"],
        speechkit_client=mock_services["speechkit_client"],
        yandexgpt_client=mock_services["yandexgpt_client"],
        pdf_generator=mock_services["pdf_generator"],
        settings=mock_services["settings"],
        num_workers=2,
    )


@pytest.fixture
def sample_task():
    """Create a sample ProcessingTask."""
    return ProcessingTask(
        chat_id=12345,
        file_path="/tmp/test_audio.ogg",
        file_name="test_audio.ogg",
        message_id=42,
    )


class TestProcessingTask:
    def test_task_creation(self):
        task = ProcessingTask(
            chat_id=12345,
            file_path="/tmp/audio.ogg",
            file_name="audio.ogg",
            message_id=1,
        )
        assert task.chat_id == 12345
        assert task.file_path == "/tmp/audio.ogg"
        assert task.file_name == "audio.ogg"
        assert task.message_id == 1
        assert task.task_id is not None
        assert len(task.task_id) == 8

    def test_task_unique_ids(self):
        t1 = ProcessingTask(chat_id=1, file_path="a", file_name="a", message_id=1)
        t2 = ProcessingTask(chat_id=1, file_path="a", file_name="a", message_id=1)
        assert t1.task_id != t2.task_id

    def test_task_has_timestamp(self):
        task = ProcessingTask(chat_id=1, file_path="a", file_name="a", message_id=1)
        assert task.enqueued_at > 0


class TestTaskQueueEnqueue:
    async def test_enqueue_returns_position(self, task_queue, sample_task):
        position = await task_queue.enqueue(sample_task)
        assert position >= 1

    async def test_enqueue_multiple(self, task_queue):
        t1 = ProcessingTask(chat_id=1, file_path="a", file_name="a", message_id=1)
        t2 = ProcessingTask(chat_id=2, file_path="b", file_name="b", message_id=2)
        await task_queue.enqueue(t1)
        pos2 = await task_queue.enqueue(t2)
        assert pos2 == 2

    async def test_get_queue_size(self, task_queue, sample_task):
        assert task_queue.get_queue_size() == 0
        await task_queue.enqueue(sample_task)
        assert task_queue.get_queue_size() == 1


class TestTaskQueueWorkers:
    async def test_start_creates_workers(self, task_queue):
        await task_queue.start()
        assert len(task_queue._workers) == 2
        await task_queue.stop()

    async def test_stop_cancels_workers(self, task_queue):
        await task_queue.start()
        await task_queue.stop()
        assert len(task_queue._workers) == 0

    async def test_worker_processes_task(self, task_queue, sample_task, mock_services):
        """Worker should pick up and process enqueued tasks."""
        # Mock os.path.exists and os.remove to avoid filesystem access
        with patch("src.services.queue.os.makedirs"), \
             patch("src.services.queue.os.path.exists", return_value=False), \
             patch("src.services.queue.os.path.isdir", return_value=False), \
             patch("src.services.queue.os.remove"):

            # Mock repo calls
            mock_user = MagicMock()
            mock_user.id = 1

            mock_transcription = MagicMock()
            mock_transcription.id = 10

            with patch("src.services.queue.repo.get_or_create_user", new_callable=AsyncMock, return_value=mock_user), \
                 patch("src.services.queue.repo.save_transcription", new_callable=AsyncMock, return_value=mock_transcription):

                await task_queue.start()
                await task_queue.enqueue(sample_task)

                # Wait for processing
                await asyncio.sleep(0.5)
                await task_queue.stop()

            # Verify pipeline steps were called
            mock_services["audio_processor"].convert_to_ogg.assert_called_once()
            mock_services["audio_processor"].get_duration.assert_called_once()
            mock_services["storage_client"].upload_file.assert_called_once()
            mock_services["speechkit_client"].recognize.assert_called_once()
            mock_services["yandexgpt_client"].analyze.assert_called_once()


class TestTaskQueueSendMessage:
    async def test_send_message(self, task_queue):
        await task_queue._send_message(12345, "Test message")
        task_queue._bot.send_message.assert_called_once_with(
            chat_id=12345, text="Test message"
        )

    async def test_send_message_error_handled(self, task_queue):
        """Send message should not raise even if bot raises."""
        task_queue._bot.send_message.side_effect = Exception("Network error")
        # Should not raise
        await task_queue._send_message(12345, "Test")


class TestCostConstant:
    def test_cost_per_sec(self):
        assert SPEECHKIT_COST_PER_SEC == 0.002542

    def test_cost_30_min(self):
        cost = 30 * 60 * SPEECHKIT_COST_PER_SEC
        assert 4.5 < cost < 4.7


class TestTimeoutMonitor:
    async def test_timeout_monitor_sends_notification(self, task_queue):
        """Timeout monitor should send a message after expected time."""
        import time

        # Patch sleep to return immediately
        with patch("src.services.queue.asyncio.sleep", new_callable=AsyncMock):
            with patch("src.services.queue.time.time", return_value=time.time() + 600):
                await task_queue._timeout_monitor(12345, 120.0, time.time())

        task_queue._bot.send_message.assert_called_once()
        call_args = task_queue._bot.send_message.call_args
        assert "больше времени" in call_args.kwargs.get("text", call_args[1].get("text", ""))
