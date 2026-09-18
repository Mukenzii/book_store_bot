import asyncio
import logging
import time
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from bot import admins
from bot.config import settings
from bot.database import engine, init_db
from bot.handlers import get_root_router
from bot.healthcheck import HEARTBEAT_FILE
from bot.middlewares import RegisterUserMiddleware, ThrottleMiddleware
from bot.scheduler import scheduler_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def _on_error(event: ErrorEvent) -> bool:
    """Catch-all handler so a single failing update never bubbles up as a
    traceback that spams the log or interrupts the dispatcher.

    On this VPS the outbound link to Telegram is flaky, which produces two
    harmless-but-noisy failures we swallow quietly:
      * "query is too old / query ID is invalid" — a callback.answer() that
        arrived after the ~15s Telegram window because the network stalled; the
        user's tap is stale, nothing to do.
      * TelegramNetworkError — a transient timeout; aiogram already retries.
    Anything else is logged with a traceback so real bugs still surface.
    Returning True marks the error handled.
    """
    exc = event.exception
    msg = str(exc)
    if isinstance(exc, TelegramBadRequest) and (
        "query is too old" in msg or "query ID is invalid" in msg
    ):
        return True
    if isinstance(exc, TelegramNetworkError):
        logger.warning("Transient Telegram network error: %s", exc)
        return True
    logger.exception("Unhandled error while processing an update: %s", exc)
    return True


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


async def _start_webhook(bot: Bot, dp: Dispatcher):
    """Register the webhook + start the aiohttp server. Returns the AppRunner.

    Telegram pushes updates to us, so there is no long-poll connection to time
    out — this eliminates the periodic 'Request timeout' / expired-callback
    errors that happen on a flaky outbound connection.
    """
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    # Retry set_webhook to ride out a transient DNS blip resolving
    # api.telegram.org right after the container starts.
    for attempt in range(1, 7):
        try:
            await bot.set_webhook(
                url=settings.full_webhook_url,
                secret_token=settings.resolved_secret,
                drop_pending_updates=True,
                allowed_updates=dp.resolve_used_update_types(),
            )
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 6:
                raise
            logger.warning("set_webhook attempt %d/6 failed: %s — retrying in 3s", attempt, exc)
            await asyncio.sleep(3)

    app = web.Application()

    async def health(_request):
        return web.Response(text="ok")

    app.router.add_get("/healthz", health)
    SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=settings.resolved_secret
    ).register(app, path=settings.webhook_path)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.web_port)
    await site.start()
    logger.info(
        "Webhook mode: %s  (listening on :%s)", settings.full_webhook_url, settings.web_port
    )
    return runner


async def main() -> None:
    _require_token()

    from aiogram.client.session.aiohttp import AiohttpSession

    # Cap the client timeout at 20s. When the link to Telegram STALLS mid-request
    # (packet loss), the default 60s timeout is what made getUpdates hang ~70s
    # before reconnecting — the ~1-minute lag. A normal long-poll returns in
    # <=10s (polling_timeout), well under this. Proxy is set when configured —
    # the real cure for the unreliable route.
    proxy = settings.telegram_proxy.strip() or None
    session = AiohttpSession(proxy=proxy, timeout=20)
    if proxy:
        logger.info("Telegram API traffic is routed through a proxy.")

    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(ThrottleMiddleware())      # drop duplicate bursts first
    dp.update.outer_middleware(RegisterUserMiddleware())
    dp.errors.register(_on_error)
    dp.include_router(get_root_router())

    await init_db()
    await admins.load()  # warm the dynamic-admin cache
    logger.info("Database ready. Starting Book Store bot…")

    heartbeat = asyncio.create_task(_heartbeat())
    scheduler = asyncio.create_task(scheduler_loop(bot))
    runner = None
    try:
        if settings.use_webhook:
            try:
                runner = await _start_webhook(bot, dp)
            except Exception as exc:  # noqa: BLE001 — keep the bot alive
                logger.error(
                    "Webhook setup FAILED: %s. Falling back to polling. "
                    "Check that %s has a DNS A record pointing to this server "
                    "and ports 80/443 are open.",
                    exc, settings.webhook_url,
                )
        if runner is not None:
            await asyncio.Event().wait()  # serve until the process is stopped
        else:
            await bot.delete_webhook(drop_pending_updates=True)
            # This VPS's link to Telegram intermittently stalls. A shorter
            # long-poll window means a dead connection is detected and retried
            # in ~10s instead of ~25s, so the "no replies then a burst" dead
            # windows shrink. Real cure is a proxy with a clean route to
            # Telegram (settings.telegram_proxy); this only limits the damage.
            # An update that actually exists still returns immediately — the
            # timeout only bounds *empty* polls and failure detection.
            await dp.start_polling(bot, polling_timeout=10)
    finally:
        # Graceful shutdown: stop background tasks, tear down the web server,
        # close the bot session and the DB connection pool.
        heartbeat.cancel()
        scheduler.cancel()
        if runner is not None:
            await runner.cleanup()
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
