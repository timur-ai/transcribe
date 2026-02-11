"""SQLAlchemy async models for the transcribe bot."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all models."""
    pass


class User(Base):
    """Authorized bot users."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    is_authorized: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transcriptions: Mapped[list["Transcription"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="desc(Transcription.created_at)",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, chat_id={self.chat_id}, authorized={self.is_authorized})>"


class Transcription(Base):
    """Stored transcription results with analysis."""

    __tablename__ = "transcriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=True)
    transcription_text: Mapped[str] = mapped_column(Text, nullable=True)
    analysis_text: Mapped[str] = mapped_column(Text, nullable=True)
    cost_rubles: Mapped[float] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="transcriptions")

    def __repr__(self) -> str:
        return f"<Transcription(id={self.id}, file={self.file_name}, user_id={self.user_id})>"


def create_db_engine(database_url: str):
    """Create an async database engine."""
    return create_async_engine(database_url, echo=False)


def create_session_factory(engine):
    """Create an async session factory."""
    return async_sessionmaker(engine, expire_on_commit=False)
