"""Unit tests for database models."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, Transcription, User


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


class TestUserModel:
    """Tests for the User model."""

    async def test_create_user(self, async_session: AsyncSession):
        user = User(chat_id=12345, is_authorized=False)
        async_session.add(user)
        await async_session.flush()

        assert user.id is not None
        assert user.chat_id == 12345
        assert user.is_authorized is False

    async def test_user_defaults(self, async_session: AsyncSession):
        user = User(chat_id=99999)
        async_session.add(user)
        await async_session.flush()

        assert user.is_authorized is False

    async def test_user_repr(self):
        user = User(id=1, chat_id=123, is_authorized=True)
        assert "chat_id=123" in repr(user)
        assert "authorized=True" in repr(user)

    async def test_chat_id_unique(self, async_session: AsyncSession):
        user1 = User(chat_id=111)
        user2 = User(chat_id=111)
        async_session.add(user1)
        await async_session.flush()
        async_session.add(user2)
        with pytest.raises(Exception):
            await async_session.flush()


class TestTranscriptionModel:
    """Tests for the Transcription model."""

    async def test_create_transcription(self, async_session: AsyncSession):
        user = User(chat_id=100, is_authorized=True)
        async_session.add(user)
        await async_session.flush()

        t = Transcription(
            user_id=user.id,
            file_name="test.mp3",
            file_type="audio",
            duration_seconds=120.5,
            transcription_text="Hello world",
            analysis_text="Summary: greeting",
            cost_rubles=0.31,
        )
        async_session.add(t)
        await async_session.flush()

        assert t.id is not None
        assert t.user_id == user.id
        assert t.file_name == "test.mp3"
        assert t.duration_seconds == 120.5

    async def test_transcription_repr(self):
        t = Transcription(id=1, file_name="test.ogg", user_id=5)
        assert "test.ogg" in repr(t)

    async def test_user_transcription_relationship(self, async_session: AsyncSession):
        user = User(chat_id=200, is_authorized=True)
        async_session.add(user)
        await async_session.flush()

        t1 = Transcription(user_id=user.id, file_name="a.ogg", file_type="audio")
        t2 = Transcription(user_id=user.id, file_name="b.mp4", file_type="video")
        async_session.add_all([t1, t2])
        await async_session.flush()

        stmt = select(User).where(User.chat_id == 200)
        result = await async_session.execute(stmt)
        fetched_user = result.scalar_one()
        transcriptions = await fetched_user.awaitable_attrs.transcriptions
        assert len(transcriptions) == 2

    async def test_transcription_nullable_fields(self, async_session: AsyncSession):
        user = User(chat_id=300, is_authorized=True)
        async_session.add(user)
        await async_session.flush()

        t = Transcription(user_id=user.id, file_name="x.ogg", file_type="audio")
        async_session.add(t)
        await async_session.flush()

        assert t.duration_seconds is None
        assert t.transcription_text is None
        assert t.analysis_text is None
        assert t.cost_rubles is None
