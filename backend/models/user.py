from datetime import date, datetime, time, timezone

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("login", name="uq_users_login"),)

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255))
    real_name: Mapped[str] = mapped_column(String(255))
    login: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(nullable=True)
    birth_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    zodiac_sign: Mapped[str | None] = mapped_column(String(50))
    birth_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(50), nullable=True)
    free_requests_left: Mapped[int] = mapped_column(Integer, default=3, server_default=text("3"))
    subscription_ends_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    sessions: Mapped[list["TarotSession"]] = relationship(back_populates="user")


class TarotSession(Base):
    __tablename__ = "tarot_sessions"
    __table_args__ = (
        Index("ix_tarot_sessions_user_status_created", "user_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(50), default="active", server_default="active")
    cycle_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    synthesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    spread_name: Mapped[str] = mapped_column(String(100), default="one-card", server_default="one-card")
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="sessions")
    readings: Mapped[list["ReadingCycle"]] = relationship(back_populates="session")


class ReadingCycle(Base):
    __tablename__ = "reading_cycles"
    __table_args__ = (
        UniqueConstraint("session_id", "cycle_number", name="uq_reading_cycles_session_cycle"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tarot_sessions.id", ondelete="CASCADE")
    )
    cycle_number: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    card_id: Mapped[int] = mapped_column(Integer)
    card_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    interpretation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    session: Mapped["TarotSession"] = relationship(back_populates="readings")
