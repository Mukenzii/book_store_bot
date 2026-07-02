from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """A Telegram user who has interacted with the bot (broadcast audience)."""

    __tablename__ = "users"

    # Telegram user id — can exceed 32-bit, so BigInteger. Used as PK directly.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Shared by the user via the "send phone" button on first /start.
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Flipped to False when the user blocks the bot, so broadcasts skip them.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Store(Base):
    """A physical book store the user can be routed to."""

    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    # Many imported rows only have a map pin, not a street address — so optional.
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    working_hours: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)


class Setting(Base):
    """Simple key/value store (used for the enabled weekly schedule days)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", server_default="")


class ScheduledPost(Base):
    """A message scheduled to broadcast to all users on a given weekday/time.

    The content is referenced by (from_chat_id, message_id) — the admin's own
    message — so any content type (text, photo, caption) is preserved via
    copy_message at send time. `preview` is a short label for the admin list.
    """

    __tablename__ = "scheduled_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    weekday: Mapped[int] = mapped_column(Integer)  # 0=Mon … 6=Sun (datetime.weekday())
    send_time: Mapped[str] = mapped_column(String(5))  # "HH:MM"
    from_chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    preview: Mapped[str] = mapped_column(String(120), default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Date the post was last broadcast — prevents double-sending within a day.
    last_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
