"""Authorization middleware — checks password and user auth status."""

import functools
import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.db.repository import is_user_authorized

logger = logging.getLogger(__name__)


def require_auth(func):
    """Decorator that checks if the user is authorized before executing the handler.

    If the user is not authorized, sends a message asking them to authorize.
    Requires ``db_session_factory`` to be stored in ``context.bot_data``.
    """

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_chat:
            return

        chat_id = update.effective_chat.id
        session_factory = context.bot_data.get("db_session_factory")

        if session_factory is None:
            logger.error("db_session_factory not found in bot_data")
            await update.effective_chat.send_message(
                "⚠️ Внутренняя ошибка. Попробуйте позже."
            )
            return

        async with session_factory() as session:
            authorized = await is_user_authorized(session, chat_id)

        if not authorized:
            await update.effective_chat.send_message(
                "🔒 Пожалуйста, авторизуйтесь. Отправьте /start"
            )
            return

        return await func(update, context)

    return wrapper
