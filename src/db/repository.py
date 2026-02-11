"""Database repository — CRUD operations for users and transcriptions."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Transcription, User


async def get_or_create_user(session: AsyncSession, chat_id: int) -> User:
    """Get an existing user or create a new one (unauthorized by default)."""
    stmt = select(User).where(User.chat_id == chat_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        user = User(chat_id=chat_id, is_authorized=False)
        session.add(user)
        await session.flush()
    return user


async def authorize_user(session: AsyncSession, chat_id: int, max_users: int = 20) -> tuple[bool, str]:
    """Authorize a user. Returns (success, message).

    Checks:
    - If user is already authorized → success.
    - If max user limit is reached → failure.
    """
    user = await get_or_create_user(session, chat_id)

    if user.is_authorized:
        return True, "already_authorized"

    count = await get_authorized_user_count(session)
    if count >= max_users:
        return False, "user_limit_reached"

    user.is_authorized = True
    await session.flush()
    return True, "authorized"


async def deauthorize_user(session: AsyncSession, chat_id: int) -> bool:
    """Deauthorize a user. Returns True if user existed and was deauthorized."""
    stmt = select(User).where(User.chat_id == chat_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        return False
    user.is_authorized = False
    await session.flush()
    return True


async def is_user_authorized(session: AsyncSession, chat_id: int) -> bool:
    """Check if a user is authorized."""
    stmt = select(User.is_authorized).where(User.chat_id == chat_id)
    result = await session.execute(stmt)
    authorized = result.scalar_one_or_none()
    return authorized is True


async def get_authorized_user_count(session: AsyncSession) -> int:
    """Get the number of currently authorized users."""
    stmt = select(func.count()).select_from(User).where(User.is_authorized == True)  # noqa: E712
    result = await session.execute(stmt)
    return result.scalar_one()


async def save_transcription(
    session: AsyncSession,
    user_id: int,
    file_name: str,
    file_type: str,
    duration_seconds: float | None = None,
    transcription_text: str | None = None,
    analysis_text: str | None = None,
    cost_rubles: float | None = None,
) -> Transcription:
    """Save a new transcription record."""
    transcription = Transcription(
        user_id=user_id,
        file_name=file_name,
        file_type=file_type,
        duration_seconds=duration_seconds,
        transcription_text=transcription_text,
        analysis_text=analysis_text,
        cost_rubles=cost_rubles,
    )
    session.add(transcription)
    await session.flush()
    return transcription


async def get_user_transcriptions(
    session: AsyncSession,
    chat_id: int,
    limit: int = 10,
    offset: int = 0,
) -> list[Transcription]:
    """Get transcription history for a user (newest first)."""
    stmt = (
        select(Transcription)
        .join(User)
        .where(User.chat_id == chat_id)
        .order_by(Transcription.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_transcription_by_id(
    session: AsyncSession,
    transcription_id: int,
) -> Transcription | None:
    """Get a single transcription by its ID."""
    stmt = select(Transcription).where(Transcription.id == transcription_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
