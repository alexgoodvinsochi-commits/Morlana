from datetime import date, datetime, time, timezone

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, Time
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255))
    real_name: Mapped[str] = mapped_column(String(255))
    birth_date: Mapped[date | None] = mapped_column(nullable=True)
    birth_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    zodiac_sign: Mapped[str | None] = mapped_column(String(50))
    birth_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(50), nullable=True)
    free_requests_left: Mapped[int] = mapped_column(Integer, default=3)
    subscription_ends_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    sessions: Mapped[list["TarotSession"]] = relationship(back_populates="user")


class TarotSession(Base):
    __tablename__ = "tarot_sessions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(50), default="active")
    cycle_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship(back_populates="sessions")
    messages: Mapped[list["ChatHistory"]] = relationship(back_populates="session")
    readings: Mapped[list["ReadingCycle"]] = relationship(back_populates="session")


class ReadingCycle(Base):
    __tablename__ = "reading_cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tarot_sessions.id", ondelete="CASCADE")
    )
    cycle_number: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    card_id: Mapped[int] = mapped_column(Integer)
    interpretation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    session: Mapped["TarotSession"] = relationship(back_populates="readings")


class ChatHistory(Base):
    __tablename__ = "chat_histories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tarot_sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    session: Mapped["TarotSession"] = relationship(back_populates="messages")
