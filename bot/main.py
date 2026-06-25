import asyncio
import logging
import time
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.database import engine, init_db
from bot.handlers import get_root_router
from bot.healthcheck import HEARTBEAT_FILE
from bot.middlewares import RegisterUserMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def _require_token() -> None:
    token = (settings.bot_token or "").strip()
    if not token or "PASTE_YOUR" in token or ":" not in token:
        logger.error("=" * 70)
        logger.error("BOT_TOKEN is missing or still the placeholder.")
        logger.error("Open .env, replace the BOT_TOKEN line with the token from")
        logger.error("@BotFather (looks like 123456789:AAE...), then run:")
        logger.error("    docker compose up -d --build")
        logger.error("=" * 70)
        raise SystemExit(1)


async def _heartbeat() -> None:
    """Touch the heartbeat file so the container health check sees us alive."""
    while True:
        try:
            Path(HEARTBEAT_FILE).write_text(str(int(time.time())))
        except OSError:
            pass
        await asyncio.sleep(30)


async def main() -> None:
    _require_token()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(RegisterUserMiddleware())
    dp.include_router(get_root_router())

    await init_db()
    logger.info("Database ready. Starting Book Store bot…")

    heartbeat = asyncio.create_task(_heartbeat())
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        # Graceful shutdown: stop the heartbeat, close the bot session and the
        # DB connection pool so we don't leak sockets on SIGTERM.
        heartbeat.cancel()
        await bot.session.close()
        await engine.dispose()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
    # SystemExit (e.g. bad config) is intentionally not caught here so the
    # process exits non-zero with the explanatory log above still visible.
