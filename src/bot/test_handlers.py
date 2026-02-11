"""Unit tests for Telegram bot handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram.ext import ConversationHandler

from src.bot.handlers import (
    AWAITING_PASSWORD,
    SPEECHKIT_COST_PER_SEC,
    start_handler,
    password_handler,
    get_conversation_handler,
    register_handlers,
)


def _make_update(chat_id=12345, text=None):
    """Create a mock Telegram Update."""
    update = MagicMock()
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_chat.send_message = AsyncMock()
    update.message = MagicMock()
    update.message.text = text or ""
    update.message.reply_text = AsyncMock()
    update.message.message_id = 42
    update.message.audio = None
    update.message.voice = None
    update.message.video = None
    update.message.video_note = None
    update.message.document = None
    return update


def _make_context(is_authorized=False, password="changeme", max_users=20):
    """Create a mock context with all required bot_data."""
    ctx = MagicMock()

    settings = MagicMock()
    settings.bot_access_password = password
    settings.max_users = max_users
    settings.tmp_dir = "/tmp/test"

    factory = MagicMock()
    session = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = cm

    ctx.bot_data = {
        "settings": settings,
        "db_session_factory": factory,
    }

    return ctx, session


class TestStartHandler:
    async def test_no_effective_chat(self):
        """Should return END if no effective_chat."""
        update = MagicMock()
        update.effective_chat = None
        ctx, _ = _make_context()

        result = await start_handler(update, ctx)
        assert result == ConversationHandler.END

    async def test_already_authorized(self):
        """Authorized user should get 'already authorized' message."""
        update = _make_update()
        ctx, session = _make_context()

        with patch("src.bot.handlers.repo.is_user_authorized", new_callable=AsyncMock, return_value=True):
            result = await start_handler(update, ctx)

        assert result == ConversationHandler.END
        update.effective_chat.send_message.assert_called_once()
        msg = update.effective_chat.send_message.call_args[0][0]
        assert "уже авторизованы" in msg

    async def test_not_authorized_asks_password(self):
        """Unauthorized user should be asked for password."""
        update = _make_update()
        ctx, session = _make_context()

        with patch("src.bot.handlers.repo.is_user_authorized", new_callable=AsyncMock, return_value=False):
            result = await start_handler(update, ctx)

        assert result == AWAITING_PASSWORD
        update.effective_chat.send_message.assert_called_once()
        msg = update.effective_chat.send_message.call_args[0][0]
        assert "пароль" in msg.lower()


class TestPasswordHandler:
    async def test_no_message(self):
        """Should return END if no message."""
        update = MagicMock()
        update.message = None
        update.effective_chat = MagicMock()
        ctx, _ = _make_context()

        result = await password_handler(update, ctx)
        assert result == ConversationHandler.END

    async def test_wrong_password(self):
        """Wrong password should ask again."""
        update = _make_update(text="wrong_password")
        ctx, session = _make_context(password="correct_password")

        result = await password_handler(update, ctx)

        assert result == AWAITING_PASSWORD
        update.effective_chat.send_message.assert_called_once()
        msg = update.effective_chat.send_message.call_args[0][0]
        assert "Неверный пароль" in msg

    async def test_correct_password_authorized(self):
        """Correct password should authorize user."""
        update = _make_update(text="changeme")
        ctx, session = _make_context(password="changeme")

        with patch("src.bot.handlers.repo.authorize_user", new_callable=AsyncMock, return_value=(True, "authorized")):
            result = await password_handler(update, ctx)

        assert result == ConversationHandler.END
        update.effective_chat.send_message.assert_called_once()
        msg = update.effective_chat.send_message.call_args[0][0]
        assert "авторизованы" in msg.lower() or "Добро пожаловать" in msg

    async def test_user_limit_reached(self):
        """Should reject when user limit is reached."""
        update = _make_update(text="changeme")
        ctx, session = _make_context(password="changeme", max_users=2)

        with patch("src.bot.handlers.repo.authorize_user", new_callable=AsyncMock, return_value=(False, "user_limit_reached")):
            result = await password_handler(update, ctx)

        assert result == ConversationHandler.END
        update.effective_chat.send_message.assert_called_once()
        msg = update.effective_chat.send_message.call_args[0][0]
        assert "лимит" in msg.lower()

    async def test_password_with_whitespace(self):
        """Password with extra whitespace should be stripped."""
        update = _make_update(text="  changeme  ")
        ctx, session = _make_context(password="changeme")

        with patch("src.bot.handlers.repo.authorize_user", new_callable=AsyncMock, return_value=(True, "authorized")):
            result = await password_handler(update, ctx)

        assert result == ConversationHandler.END


class TestConversationHandler:
    def test_conversation_handler_created(self):
        """Should create a valid ConversationHandler."""
        handler = get_conversation_handler()
        assert isinstance(handler, ConversationHandler)

    def test_conversation_handler_has_states(self):
        """Should have AWAITING_PASSWORD state."""
        handler = get_conversation_handler()
        assert AWAITING_PASSWORD in handler.states


class TestRegisterHandlers:
    def test_register_handlers_adds_handlers(self):
        """Should register all handlers on the application."""
        app = MagicMock()
        register_handlers(app)
        # At least: conversation, help, history, logout, cost, pdf callback, history callback, file, unknown
        assert app.add_handler.call_count >= 7


class TestCostConstants:
    def test_speechkit_cost_per_sec(self):
        """Cost constant should match expected value."""
        assert SPEECHKIT_COST_PER_SEC == 0.002542

    def test_cost_calculation_30_min(self):
        """30 minutes should cost approximately 4.58 RUB."""
        cost = 30 * 60 * SPEECHKIT_COST_PER_SEC
        assert abs(cost - 4.576) < 0.01
