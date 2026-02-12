"""Telegram bot command and message handlers."""

import html
import logging
import os
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from src.bot.keyboards import get_history_keyboard, get_pdf_keyboard
from src.bot.middleware import require_auth
from src.db import repository as repo
from src.services.audio import AudioProcessor

logger = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return html.escape(text)

# Conversation states
AWAITING_PASSWORD = 0

# Cost per second (deferred mode)
SPEECHKIT_COST_PER_SEC = 0.002542


# ── /start and password ──────────────────────────────────


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start command — ask for password."""
    if not update.effective_chat:
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    session_factory = context.bot_data["db_session_factory"]

    async with session_factory() as session:
        authorized = await repo.is_user_authorized(session, chat_id)

    if authorized:
        await update.effective_chat.send_message(
            "✅ Вы уже авторизованы! Отправьте аудио или видеофайл для транскрибации.\n"
            "Используйте /help для справки."
        )
        return ConversationHandler.END

    await update.effective_chat.send_message(
        "👋 Добро пожаловать в Transcribe Bot!\n\n"
        "🔒 Для доступа введите пароль:"
    )
    return AWAITING_PASSWORD


async def password_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle password input during authorization."""
    if not update.message or not update.effective_chat:
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    password_input = update.message.text.strip()
    settings = context.bot_data["settings"]
    session_factory = context.bot_data["db_session_factory"]

    if password_input != settings.bot_access_password:
        await update.effective_chat.send_message(
            "❌ Неверный пароль. Попробуйте ещё раз:"
        )
        return AWAITING_PASSWORD

    async with session_factory() as session:
        success, msg = await repo.authorize_user(
            session, chat_id, max_users=settings.max_users
        )
        await session.commit()

    if not success:
        await update.effective_chat.send_message(
            "😔 К сожалению, достигнут лимит пользователей "
            f"({settings.max_users}). Обратитесь к администратору."
        )
        return ConversationHandler.END

    await update.effective_chat.send_message(
        "✅ Добро пожаловать! Вы авторизованы.\n\n"
        "📎 Отправьте аудио или видеофайл для транскрибации.\n"
        "Используйте /help для получения справки."
    )
    return ConversationHandler.END


# ── /help ─────────────────────────────────────────────────


@require_auth
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command — show usage instructions."""
    await update.effective_chat.send_message(
        "📖 <b>Transcribe Bot — Справка</b>\n\n"
        "<b>Как использовать:</b>\n"
        "1. Отправьте аудио или видеофайл боту\n"
        "2. Дождитесь транскрибации и анализа\n"
        "3. Получите результат с возможностью скачать PDF\n\n"
        "<b>Поддерживаемые форматы:</b>\n"
        "🎵 Аудио: OGG, MP3, WAV, FLAC, M4A\n"
        "🎬 Видео: MP4, AVI, MOV, MKV, WEBM\n\n"
        "💡 <i>Для файлов &gt; 20 МБ отправляйте как документ</i>\n\n"
        "<b>Команды:</b>\n"
        "/start — авторизация\n"
        "/help — эта справка\n"
        "/history — история транскрибаций\n"
        "/cost — стоимость последней транскрибации\n"
        "/logout — выход из системы\n\n"
        "<b>Ограничения:</b>\n"
        "• Макс. длительность: 4 часа\n"
        "• Макс. размер файла: 2 ГБ (лимит Telegram)\n"
        "• Язык: только русский",
        parse_mode="HTML",
    )


# ── /history ──────────────────────────────────────────────


@require_auth
async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /history command — show transcription history."""
    chat_id = update.effective_chat.id
    session_factory = context.bot_data["db_session_factory"]

    async with session_factory() as session:
        transcriptions = await repo.get_user_transcriptions(session, chat_id, limit=50)

    if not transcriptions:
        await update.effective_chat.send_message("📭 У вас пока нет транскрибаций.")
        return

    keyboard = get_history_keyboard(transcriptions, page=0)
    await update.effective_chat.send_message(
        f"📋 <b>История транскрибаций</b> ({len(transcriptions)} шт.)",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@require_auth
async def history_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle history item selection — show full transcription."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("history:"):
        transcription_id = int(data.split(":")[1])
        session_factory = context.bot_data["db_session_factory"]

        async with session_factory() as session:
            t = await repo.get_transcription_by_id(session, transcription_id)

        if not t:
            await query.edit_message_text("❌ Транскрибация не найдена.")
            return

        name = _escape_html(t.file_name)
        text = f"📝 <b>{name}</b>\n\n"
        if t.transcription_text:
            trans_text = _escape_html(t.transcription_text[:3500])
            text += f"<b>Транскрибация:</b>\n{trans_text}\n\n"
        if t.analysis_text:
            analysis = _escape_html(t.analysis_text[:3500])
            text += f"<b>Анализ:</b>\n{analysis}"

        keyboard = get_pdf_keyboard(t.id)
        await query.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

    elif data.startswith("hpage:"):
        page = int(data.split(":")[1])
        chat_id = update.effective_chat.id
        session_factory = context.bot_data["db_session_factory"]

        async with session_factory() as session:
            transcriptions = await repo.get_user_transcriptions(session, chat_id, limit=50)

        keyboard = get_history_keyboard(transcriptions, page=page)
        await query.edit_message_reply_markup(reply_markup=keyboard)


# ── /logout ───────────────────────────────────────────────


@require_auth
async def logout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /logout command — deauthorize user."""
    chat_id = update.effective_chat.id
    session_factory = context.bot_data["db_session_factory"]

    async with session_factory() as session:
        await repo.deauthorize_user(session, chat_id)
        await session.commit()

    await update.effective_chat.send_message(
        "👋 Вы вышли из системы.\n"
        "Для повторного входа отправьте /start"
    )


# ── /cost ─────────────────────────────────────────────────


@require_auth
async def cost_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cost command — show cost of last transcription."""
    chat_id = update.effective_chat.id
    session_factory = context.bot_data["db_session_factory"]

    async with session_factory() as session:
        transcriptions = await repo.get_user_transcriptions(session, chat_id, limit=1)

    if not transcriptions:
        await update.effective_chat.send_message("📭 У вас нет транскрибаций для расчёта.")
        return

    t = transcriptions[0]
    duration = t.duration_seconds or 0
    speechkit_cost = duration * SPEECHKIT_COST_PER_SEC
    gpt_cost_estimate = 2.0  # rough estimate
    total = speechkit_cost + gpt_cost_estimate

    name = _escape_html(t.file_name)
    await update.effective_chat.send_message(
        f"💰 <b>Стоимость последней транскрибации</b>\n\n"
        f"Файл: {name}\n"
        f"Длительность: {duration / 60:.1f} мин\n\n"
        f"SpeechKit: ~{speechkit_cost:.2f} ₽\n"
        f"YandexGPT: ~{gpt_cost_estimate:.2f} ₽\n"
        f"<b>Итого: ~{total:.2f} ₽</b>",
        parse_mode="HTML",
    )


# ── File handler ──────────────────────────────────────────


@require_auth
async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming audio, video, voice, video_note, and document messages."""
    message = update.message
    if not message:
        return

    # Determine file info
    file_obj = None
    file_name = "unknown"

    if message.audio:
        file_obj = message.audio
        file_name = message.audio.file_name or f"audio.{message.audio.mime_type.split('/')[-1]}"
    elif message.voice:
        file_obj = message.voice
        file_name = "voice.ogg"
    elif message.video:
        file_obj = message.video
        file_name = message.video.file_name or "video.mp4"
    elif message.video_note:
        file_obj = message.video_note
        file_name = "video_note.mp4"
    elif message.document:
        file_obj = message.document
        file_name = message.document.file_name or "document"
        if not AudioProcessor.is_supported(file_name):
            await message.reply_text(
                "❌ Неподдерживаемый формат файла.\n"
                "Отправьте аудио (OGG, MP3, WAV, FLAC, M4A) или видео (MP4, AVI, MOV, MKV, WEBM)."
            )
            return

    if file_obj is None:
        return

    # Check file size (Telegram already limits to 2GB for documents)
    file_size = file_obj.file_size or 0
    if file_size > 2 * 1024 * 1024 * 1024:  # 2 GB
        await message.reply_text("❌ Файл слишком большой. Максимальный размер — 2 ГБ.")
        return

    # Download file
    await message.reply_text("⏳ Файл получен, начинаю обработку...")

    tmp_dir = context.bot_data["settings"].tmp_dir
    os.makedirs(tmp_dir, exist_ok=True)
    local_path = os.path.join(tmp_dir, f"{update.effective_chat.id}_{file_name}")

    try:
        tg_file = await file_obj.get_file()
        await tg_file.download_to_drive(local_path)
    except Exception as e:
        logger.error("Failed to download file: %s", e)
        await message.reply_text("❌ Не удалось скачать файл. Попробуйте ещё раз.")
        return

    # Enqueue for processing
    task_queue = context.bot_data.get("task_queue")
    if task_queue:
        from src.services.queue import ProcessingTask

        task = ProcessingTask(
            chat_id=update.effective_chat.id,
            file_path=local_path,
            file_name=file_name,
            message_id=message.message_id,
        )
        position = await task_queue.enqueue(task)
        if position > 1:
            await message.reply_text(
                f"📋 Ваш файл добавлен в очередь. Позиция: {position}"
            )
    else:
        await message.reply_text("⚠️ Система обработки временно недоступна.")


# ── PDF callback ──────────────────────────────────────────


@require_auth
async def pdf_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle PDF download button press."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("pdf:"):
        return

    transcription_id = int(data.split(":")[1])
    session_factory = context.bot_data["db_session_factory"]

    async with session_factory() as session:
        t = await repo.get_transcription_by_id(session, transcription_id)

    if not t:
        await query.message.reply_text("❌ Транскрибация не найдена.")
        return

    # Generate PDF
    pdf_generator = context.bot_data.get("pdf_generator")
    if not pdf_generator:
        await query.message.reply_text("⚠️ Генерация PDF временно недоступна.")
        return

    try:
        pdf_path = pdf_generator.generate(
            file_name=t.file_name,
            transcription_text=t.transcription_text or "",
            analysis_text=t.analysis_text or "",
            created_at=t.created_at,
        )
        with open(pdf_path, "rb") as pdf_file:
            await query.message.reply_document(
                document=pdf_file,
                filename=f"transcription_{t.id}.pdf",
                caption="📄 Транскрибация и анализ",
            )
        # Clean up
        os.remove(pdf_path)
    except Exception as e:
        logger.error("Failed to generate PDF: %s", e)
        await query.message.reply_text("❌ Ошибка при генерации PDF. Попробуйте позже.")


# ── Unknown messages ──────────────────────────────────────


@require_auth
async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unrecognized messages from authorized users."""
    await update.effective_chat.send_message(
        "🤔 Отправьте аудио или видеофайл для транскрибации "
        "или используйте /help для справки."
    )


# ── Register handlers ────────────────────────────────────


def get_conversation_handler() -> ConversationHandler:
    """Create and return the main conversation handler for auth flow."""
    return ConversationHandler(
        entry_points=[CommandHandler("start", start_handler)],
        states={
            AWAITING_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, password_handler),
            ],
        },
        fallbacks=[
            CommandHandler("start", start_handler),
            CommandHandler("help", help_handler),
            CommandHandler("history", history_handler),
            CommandHandler("logout", logout_handler),
            CommandHandler("cost", cost_handler),
        ],
    )


def register_handlers(application) -> None:
    """Register all handlers with the application."""
    # Auth conversation (must be first)
    application.add_handler(get_conversation_handler())

    # Commands
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("history", history_handler))
    application.add_handler(CommandHandler("logout", logout_handler))
    application.add_handler(CommandHandler("cost", cost_handler))

    # Callback queries
    application.add_handler(CallbackQueryHandler(pdf_callback_handler, pattern=r"^pdf:"))
    application.add_handler(CallbackQueryHandler(history_callback_handler, pattern=r"^(history|hpage):"))

    # File handlers
    application.add_handler(MessageHandler(
        filters.AUDIO | filters.VOICE | filters.VIDEO | filters.VIDEO_NOTE | filters.Document.ALL,
        file_handler,
    ))

    # Unknown text messages
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        unknown_handler,
    ))
