import asyncio
import logging

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
            return
        except Exception as exc:  # noqa: BLE001 — broad on purpose during boot
            if attempt == retries:
                raise
            logger.warning(
                "DB not ready (attempt %d/%d): %s — retrying in %.0fs",
                attempt, retries, exc, delay,
            )
            await asyncio.sleep(delay)
