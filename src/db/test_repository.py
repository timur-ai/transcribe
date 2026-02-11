"""Unit tests for database repository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, User
from src.db import repository as repo


@pytest.fixture
async def async_session():
    """Create an in-memory SQLite async session for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


class TestGetOrCreateUser:
    async def test_creates_new_user(self, async_session: AsyncSession):
        user = await repo.get_or_create_user(async_session, chat_id=111)
        assert user.chat_id == 111
        assert user.is_authorized is False

    async def test_returns_existing_user(self, async_session: AsyncSession):
        user1 = await repo.get_or_create_user(async_session, chat_id=222)
        user2 = await repo.get_or_create_user(async_session, chat_id=222)
        assert user1.id == user2.id


class TestAuthorizeUser:
    async def test_authorize_new_user(self, async_session: AsyncSession):
        success, msg = await repo.authorize_user(async_session, chat_id=100, max_users=20)
        assert success is True
        assert msg == "authorized"
        assert await repo.is_user_authorized(async_session, 100) is True

    async def test_already_authorized(self, async_session: AsyncSession):
        await repo.authorize_user(async_session, chat_id=100, max_users=20)
        success, msg = await repo.authorize_user(async_session, chat_id=100, max_users=20)
        assert success is True
        assert msg == "already_authorized"

    async def test_user_limit_reached(self, async_session: AsyncSession):
        # Authorize 2 users with max_users=2
        await repo.authorize_user(async_session, chat_id=1, max_users=2)
        await repo.authorize_user(async_session, chat_id=2, max_users=2)

        # Third user should fail
        success, msg = await repo.authorize_user(async_session, chat_id=3, max_users=2)
        assert success is False
        assert msg == "user_limit_reached"

    async def test_user_limit_exact_boundary(self, async_session: AsyncSession):
        # Authorize exactly max_users
        for i in range(20):
            success, _ = await repo.authorize_user(async_session, chat_id=1000 + i, max_users=20)
            assert success is True

        # 21st should fail
        success, msg = await repo.authorize_user(async_session, chat_id=9999, max_users=20)
        assert success is False
        assert msg == "user_limit_reached"


class TestDeauthorizeUser:
    async def test_deauthorize_existing(self, async_session: AsyncSession):
        await repo.authorize_user(async_session, chat_id=100, max_users=20)
        result = await repo.deauthorize_user(async_session, chat_id=100)
        assert result is True
        assert await repo.is_user_authorized(async_session, 100) is False

    async def test_deauthorize_nonexistent(self, async_session: AsyncSession):
        result = await repo.deauthorize_user(async_session, chat_id=9999)
        assert result is False

    async def test_deauthorize_frees_slot(self, async_session: AsyncSession):
        await repo.authorize_user(async_session, chat_id=1, max_users=2)
        await repo.authorize_user(async_session, chat_id=2, max_users=2)

        # Limit reached
        success, _ = await repo.authorize_user(async_session, chat_id=3, max_users=2)
        assert success is False

        # Free a slot
        await repo.deauthorize_user(async_session, chat_id=1)

        # Now can authorize
        success, msg = await repo.authorize_user(async_session, chat_id=3, max_users=2)
        assert success is True
        assert msg == "authorized"


class TestIsUserAuthorized:
    async def test_authorized(self, async_session: AsyncSession):
        await repo.authorize_user(async_session, chat_id=100, max_users=20)
        assert await repo.is_user_authorized(async_session, 100) is True

    async def test_not_authorized(self, async_session: AsyncSession):
        await repo.get_or_create_user(async_session, chat_id=200)
        assert await repo.is_user_authorized(async_session, 200) is False

    async def test_nonexistent_user(self, async_session: AsyncSession):
        assert await repo.is_user_authorized(async_session, 999) is False


class TestGetAuthorizedUserCount:
    async def test_count_zero(self, async_session: AsyncSession):
        count = await repo.get_authorized_user_count(async_session)
        assert count == 0

    async def test_count_multiple(self, async_session: AsyncSession):
        await repo.authorize_user(async_session, chat_id=1, max_users=20)
        await repo.authorize_user(async_session, chat_id=2, max_users=20)
        await repo.get_or_create_user(async_session, chat_id=3)  # not authorized

        count = await repo.get_authorized_user_count(async_session)
        assert count == 2


class TestSaveTranscription:
    async def test_save_full(self, async_session: AsyncSession):
        user = await repo.get_or_create_user(async_session, chat_id=100)
        t = await repo.save_transcription(
            async_session,
            user_id=user.id,
            file_name="test.mp3",
            file_type="audio",
            duration_seconds=120.0,
            transcription_text="Hello world",
            analysis_text="Summary",
            cost_rubles=0.31,
        )
        assert t.id is not None
        assert t.file_name == "test.mp3"
        assert t.transcription_text == "Hello world"

    async def test_save_minimal(self, async_session: AsyncSession):
        user = await repo.get_or_create_user(async_session, chat_id=100)
        t = await repo.save_transcription(
            async_session,
            user_id=user.id,
            file_name="video.mp4",
            file_type="video",
        )
        assert t.id is not None
        assert t.duration_seconds is None


class TestGetUserTranscriptions:
    async def test_get_history(self, async_session: AsyncSession):
        await repo.authorize_user(async_session, chat_id=100, max_users=20)
        user = await repo.get_or_create_user(async_session, chat_id=100)

        for i in range(5):
            await repo.save_transcription(
                async_session,
                user_id=user.id,
                file_name=f"file_{i}.ogg",
                file_type="audio",
            )

        items = await repo.get_user_transcriptions(async_session, chat_id=100, limit=3)
        assert len(items) == 3

    async def test_get_empty_history(self, async_session: AsyncSession):
        items = await repo.get_user_transcriptions(async_session, chat_id=999)
        assert items == []

    async def test_pagination(self, async_session: AsyncSession):
        user = await repo.get_or_create_user(async_session, chat_id=100)
        for i in range(5):
            await repo.save_transcription(
                async_session, user_id=user.id, file_name=f"f{i}.ogg", file_type="audio"
            )

        page1 = await repo.get_user_transcriptions(async_session, chat_id=100, limit=2, offset=0)
        page2 = await repo.get_user_transcriptions(async_session, chat_id=100, limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].id != page2[0].id


class TestGetTranscriptionById:
    async def test_found(self, async_session: AsyncSession):
        user = await repo.get_or_create_user(async_session, chat_id=100)
        t = await repo.save_transcription(
            async_session, user_id=user.id, file_name="a.ogg", file_type="audio"
        )
        found = await repo.get_transcription_by_id(async_session, t.id)
        assert found is not None
        assert found.file_name == "a.ogg"

    async def test_not_found(self, async_session: AsyncSession):
        found = await repo.get_transcription_by_id(async_session, 99999)
        assert found is None
