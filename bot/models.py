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
from sqlalchemy import REAL, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
    # Refreshed on every interaction (throttled) — powers the "recently active"
    # stats. A Telegram bot only sees a user when they act, so this is the
    # closest thing to "online": last time they sent/tapped anything.
    last_seen: Mapped[datetime] = mapped_column(
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
    # The private test-mode store: hidden from customers' search and the admin
    # store list; testers are made its owner automatically.
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Book(Base):
    """A book in the catalogue. The AI assistant answers customer questions by
    retrieving relevant rows from here and passing them to the model as context
    (RAG) — so keeping this table accurate keeps the assistant accurate."""

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Imprint / publisher (Falaq Nashr distributes several: Nun nashr, Falaq
    # nashr, Eng sharafli ummat, Holis nashr, G'yosiddin Habibulloh, ...).
    publisher: Mapped[str | None] = mapped_column(String(120), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The blurb / summary — the richest signal the assistant uses to recommend.
    annotation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Text, not numeric, so it can hold "45 000 so'm" etc. as the admin typed it.
    price: Mapped[str | None] = mapped_column(String(60), nullable=True)
    language: Mapped[str | None] = mapped_column(String(60), nullable=True)
    age_group: Mapped[str | None] = mapped_column(String(60), nullable=True)
    isbn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Comma-separated free-text keywords to widen search matches.
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Filename (under book_images/) of the book's info image, sent to the user
    # when the assistant recommends this book. The image carries the details.
    image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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


class Admin(Base):
    """An admin added dynamically through the bot (in addition to ADMIN_IDS)."""

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StoreBook(Base):
    """A book a store owner says is available at their store.

    Ownership is by phone: the store's `phone` (entered by an admin) is the
    owner's key — a Telegram user whose shared phone matches it manages that
    store's books here. Each row either references a catalogue Book (`book_id`)
    or is a free-text entry; `title`/`author` are denormalised for display.
    Books are visible to customers as soon as the owner adds them.
    """

    __tablename__ = "store_books"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True)
    # Set when the owner picked a catalogue book; NULL for a free-text entry.
    book_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Unused: owner-added books go live immediately (approval was removed).
    approved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BookEdition(Base):
    """One ingested edition of a book for content Q&A (RAG).

    `edition_key` / `book_key` are our own stable IDs (the converter's IDs are
    illustrative and are only kept as `source_edition_id`). `source_sha256`
    identifies the exact PDF; `content_sha256` the ingested chunk payloads —
    a re-import with the same content is a no-op, a changed one bumps
    `content_version`. `enabled` gates serving answers from this edition.
    """

    __tablename__ = "book_editions"

    edition_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    book_key: Mapped[str] = mapped_column(String(120), index=True)
    # Title exactly as in our catalogue (books.title) — links content Q&A to it.
    catalog_title: Mapped[str] = mapped_column(String(300))
    source_title: Mapped[str] = mapped_column(String(300))
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_edition_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64))
    content_sha256: Mapped[str] = mapped_column(String(64))
    content_version: Mapped[int] = mapped_column(Integer, default=1)
    schema_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BookChunk(Base):
    """A retrievable passage of an edition. `text` is the source text, verbatim;
    `search_text` is the derived Cyrillic/Latin-insensitive key that the
    full-text index covers. `page_map` / `source_segments` are stored exactly as
    supplied so citations can be resolved to a page per character offset."""

    __tablename__ = "book_chunks"
    __table_args__ = (UniqueConstraint("edition_key", "chunk_id", name="uq_book_chunks_edition_chunk"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_key: Mapped[str] = mapped_column(String(160), index=True)
    # Stable within an edition (the suffix of the converter's id, e.g. "c00012").
    chunk_id: Mapped[str] = mapped_column(String(40))
    source_chunk_id: Mapped[str] = mapped_column(String(240))
    seq: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64))
    pdf_page_start: Mapped[int] = mapped_column(Integer)
    pdf_page_end: Mapped[int] = mapped_column(Integer)
    page_map: Mapped[list] = mapped_column(JSONB)
    source_segments: Mapped[list] = mapped_column(JSONB)
    # Optional vector for hybrid retrieval; NULL until a provider fills it.
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(REAL), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # content_version of the edition when this chunk last changed.
    content_version: Mapped[int] = mapped_column(Integer, default=1)
