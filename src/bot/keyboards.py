"""Inline keyboard builders for the Telegram bot."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_pdf_keyboard(transcription_id: int) -> InlineKeyboardMarkup:
    """Build an inline keyboard with a 'Download PDF' button.

    Args:
        transcription_id: Database ID of the transcription.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Скачать PDF", callback_data=f"pdf:{transcription_id}")]
    ])


def get_history_keyboard(
    transcriptions: list,
    page: int = 0,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard for transcription history navigation.

    Args:
        transcriptions: List of Transcription model instances.
        page: Current page number (0-indexed).
        page_size: Number of items per page.
    """
    buttons = []
    start = page * page_size
    end = start + page_size
    page_items = transcriptions[start:end]

    for t in page_items:
        label = t.file_name[:30]
        date_str = t.created_at.strftime("%d.%m %H:%M") if t.created_at else ""
        preview = ""
        if t.transcription_text:
            preview = t.transcription_text[:40].replace("\n", " ") + "…"
        btn_text = f"📝 {date_str} | {label}"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"history:{t.id}")])

    # Pagination buttons
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"hpage:{page - 1}"))
    if end < len(transcriptions):
        nav.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f"hpage:{page + 1}"))
    if nav:
        buttons.append(nav)

    return InlineKeyboardMarkup(buttons)
