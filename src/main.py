"""Application entry point — initializes bot, DB, queue, and starts polling."""

import asyncio
import logging
import os
import sys

from telegram.ext import ApplicationBuilder

from src.bot.handlers import register_handlers
from src.config import get_settings
from src.db.models import Base, create_db_engine, create_session_factory
from src.services.audio import AudioProcessor
from src.services.iam import IAMTokenManager
from src.services.pdf import PDFGenerator
from src.services.queue import TaskQueue
from src.services.speechkit import SpeechKitClient
from src.services.storage import ObjectStorageClient
from src.services.yandexgpt import YandexGPTClient

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def init_db(engine):
    """Create all tables on startup (for development). Use Alembic in production."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")


def main() -> None:
    """Start the Transcribe Bot."""
    settings = get_settings()
    logger.info("Starting Transcribe Bot...")

    # ── Database ──────────────────────────────────────────
    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    # Run DB init in event loop
    asyncio.get_event_loop().run_until_complete(init_db(engine))

    # ── Yandex Cloud services ─────────────────────────────
    iam_manager = IAMTokenManager(settings.yc_service_account_key_file)

    storage_client = ObjectStorageClient(
        access_key=settings.yc_s3_access_key,
        secret_key=settings.yc_s3_secret_key,
        bucket=settings.yc_s3_bucket,
        endpoint=settings.yc_s3_endpoint,
    )

    speechkit_client = SpeechKitClient(
        iam_manager=iam_manager,
        folder_id=settings.yc_folder_id,
        api_endpoint=settings.speechkit_api_endpoint,
    )

    yandexgpt_client = YandexGPTClient(
        iam_manager=iam_manager,
        folder_id=settings.yc_folder_id,
        model_uri=settings.yandexgpt_model_uri,
        api_endpoint=settings.yandexgpt_api_endpoint,
    )

    audio_processor = AudioProcessor()
    pdf_generator = PDFGenerator(output_dir=settings.tmp_dir)

    # ── Telegram bot ──────────────────────────────────────
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # Store shared objects in bot_data
    application.bot_data["settings"] = settings
    application.bot_data["db_session_factory"] = session_factory
    application.bot_data["pdf_generator"] = pdf_generator

    # ── Task queue ────────────────────────────────────────
    task_queue = TaskQueue(
        bot=application.bot,
        session_factory=session_factory,
        audio_processor=audio_processor,
        storage_client=storage_client,
        speechkit_client=speechkit_client,
        yandexgpt_client=yandexgpt_client,
        pdf_generator=pdf_generator,
        settings=settings,
        num_workers=settings.queue_workers,
    )
    application.bot_data["task_queue"] = task_queue

    # Register handlers
    register_handlers(application)

    # Start queue workers after bot starts
    async def post_init(app):
        await task_queue.start()
        logger.info("Task queue started with %d workers", settings.queue_workers)

    async def pre_shutdown(app):
        await task_queue.stop()
        await engine.dispose()
        logger.info("Shutdown complete")

    application.post_init = post_init
    application.post_shutdown = pre_shutdown

    # ── Run ───────────────────────────────────────────────
    logger.info("Bot is ready. Starting polling...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
