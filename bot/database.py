import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, pool_pre_ping=True)

session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db(retries: int = 10, delay: float = 2.0) -> None:
    """Create tables if they don't exist yet — safe to call on every startup.

    Retries so the bot can start before Postgres is fully accepting
    connections (e.g. a host reboot where both start at once).
    """
    # Imported here to avoid a circular import.
    from bot.models import Base

    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # Light migrations: create_all never ALTERs existing tables, so
                # add newer columns idempotently for databases created earlier.
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(32)")
                )
                # last_seen: add it NULLABLE first, then backfill from
                # created_at. Adding it with `DEFAULT now()` would stamp every
                # existing user with the deploy time, making all of them look
                # "active" at once — which is exactly the bug we're fixing.
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ")
                )
                # Fresh rows from the ADD COLUMN have NULL last_seen — seed them
                # from when the user actually joined (their real last-known
                # activity), not from now.
                await conn.execute(
                    text(
                        "UPDATE users SET last_seen = COALESCE(created_at, now()) "
                        "WHERE last_seen IS NULL"
                    )
                )
                # One-time repair for databases where the first version of this
                # migration already stamped everyone with now(). Runs exactly
                # once, guarded by a marker in settings, so genuine activity
                # recorded afterwards is never clobbered.
                repaired = await conn.scalar(
                    text("SELECT value FROM settings WHERE key = 'last_seen_repaired'")
                )
                if not repaired:
                    await conn.execute(
                        text("UPDATE users SET last_seen = COALESCE(created_at, last_seen)")
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO settings (key, value) "
                            "VALUES ('last_seen_repaired', '1') "
                            "ON CONFLICT (key) DO UPDATE SET value = '1'"
                        )
                    )
                # Now enforce the invariant for all future inserts.
                await conn.execute(
                    text("ALTER TABLE users ALTER COLUMN last_seen SET DEFAULT now()")
                )
                await conn.execute(
                    text("ALTER TABLE users ALTER COLUMN last_seen SET NOT NULL")
                )
            return
        except Exception as exc:  # noqa: BLE001 — broad on purpose during boot
            if attempt == retries:
                raise
            logger.warning(
                "DB not ready (attempt %d/%d): %s — retrying in %.0fs",
                attempt, retries, exc, delay,
            )
            await asyncio.sleep(delay)
