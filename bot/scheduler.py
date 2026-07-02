import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot

from bot import repository as repo
from bot.broadcast import broadcast_copy
from bot.config import settings
from bot.keyboards import WEEKDAY_NAMES

logger = logging.getLogger(__name__)


def local_now() -> datetime:
    """Current time in the configured schedule timezone (container runs UTC)."""
    return datetime.utcnow() + timedelta(hours=settings.schedule_tz_offset)


async def _tick(bot: Bot) -> None:
    now = local_now()
    weekday = now.weekday()
    hhmm = now.strftime("%H:%M")
    today = now.date()

    # Only send on weekdays the admin enabled.
    if weekday not in await repo.get_enabled_weekdays():
        return

    for post in await repo.due_scheduled_posts(weekday, hhmm, today):
        # Mark as sent first so a mid-broadcast crash can't double-post today.
        await repo.mark_post_sent(post.id, today)
        try:
            result = await broadcast_copy(bot, post.from_chat_id, post.message_id)
            logger.info(
                "Scheduled post #%s (%s %s) sent: %s delivered, %s blocked, %s failed",
                post.id, WEEKDAY_NAMES[post.weekday], post.send_time,
                result.sent, result.blocked, result.failed,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scheduled post #%s failed to broadcast: %s", post.id, exc)


async def scheduler_loop(bot: Bot) -> None:
    """Check once a minute for scheduled posts that are due and broadcast them."""
    logger.info("Scheduled-post scheduler started (tz offset +%sh).", settings.schedule_tz_offset)
    while True:
        try:
            await _tick(bot)
        except Exception as exc:  # noqa: BLE001 — never let the loop die
            logger.warning("Scheduler tick error: %s", exc)
        await asyncio.sleep(60)
