"""Unit tests for authorization middleware."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


from src.bot.middleware import require_auth


@pytest.fixture
def update():
    """Create a mock Telegram Update."""
    upd = MagicMock()
    upd.effective_chat = MagicMock()
    upd.effective_chat.id = 12345
    upd.effective_chat.send_message = AsyncMock()
    return upd


@pytest.fixture
def context():
    """Create a mock context with db_session_factory."""
    ctx = MagicMock()
    ctx.bot_data = {}
    return ctx


def _make_session_factory(is_authorized: bool):
    """Create a mock async session factory that returns given auth status."""
    session = AsyncMock()
    factory = MagicMock()

    # session_factory() returns context manager
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = cm

    return factory, session, is_authorized


class TestRequireAuth:
    async def test_authorized_user_passes_through(self, update, context):
        """Authorized user should have the handler called."""
        handler = AsyncMock(return_value="handler_result")
        decorated = require_auth(handler)

        factory = MagicMock()
        session = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = cm
        context.bot_data["db_session_factory"] = factory

        with patch("src.bot.middleware.is_user_authorized", new_callable=AsyncMock, return_value=True):
            result = await decorated(update, context)

        handler.assert_called_once_with(update, context)
        assert result == "handler_result"

    async def test_unauthorized_user_blocked(self, update, context):
        """Unauthorized user should get a rejection message."""
        handler = AsyncMock()
        decorated = require_auth(handler)

        factory = MagicMock()
        session = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = cm
        context.bot_data["db_session_factory"] = factory

        with patch("src.bot.middleware.is_user_authorized", new_callable=AsyncMock, return_value=False):
            result = await decorated(update, context)

        handler.assert_not_called()
        update.effective_chat.send_message.assert_called_once()
        msg = update.effective_chat.send_message.call_args[0][0]
        assert "авторизуйтесь" in msg

    async def test_no_effective_chat_returns_early(self, context):
        """If update has no effective_chat, handler should not be called."""
        handler = AsyncMock()
        decorated = require_auth(handler)

        update = MagicMock()
        update.effective_chat = None

        result = await decorated(update, context)
        handler.assert_not_called()
        assert result is None

    async def test_no_session_factory_sends_error(self, update, context):
        """If db_session_factory is missing from bot_data, send error."""
        handler = AsyncMock()
        decorated = require_auth(handler)

        # context.bot_data has no "db_session_factory"
        result = await decorated(update, context)

        handler.assert_not_called()
        update.effective_chat.send_message.assert_called_once()
        msg = update.effective_chat.send_message.call_args[0][0]
        assert "ошибка" in msg.lower() or "⚠️" in msg

    async def test_preserves_function_name(self):
        """Decorated function should preserve its original name."""
        async def my_handler(update, context):
            pass

        decorated = require_auth(my_handler)
        assert decorated.__name__ == "my_handler"
