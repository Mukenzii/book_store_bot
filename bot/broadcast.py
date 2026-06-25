import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from bot import repository as repo

logger = logging.getLogger(__name__)

# Telegram allows ~30 messages/sec to different users; stay well under it.
_DELAY = 0.05


@dataclass
class BroadcastResult:
    total: int = 0
    sent: int = 0
    blocked: int = 0
    failed: int = 0


async def broadcast_copy(bot: Bot, from_chat_id: int, message_id: int) -> BroadcastResult:
    """Copy one message (any type) to every active user.

    Uses copy_message so the original text/photo/caption/formatting is preserved
    without the "forwarded from" header. Users who blocked the bot are marked
    inactive so future broadcasts skip them.
    """
    user_ids = await repo.active_user_ids()
    result = BroadcastResult(total=len(user_ids))

    for user_id in user_ids:
        try:
            await bot.copy_message(
                chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id
            )
            result.sent += 1
        except TelegramRetryAfter as exc:
            # Hit a flood limit — wait it out and retry this user once.
            await asyncio.sleep(exc.retry_after)
            try:
                await bot.copy_message(
                    chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id
                )
                result.sent += 1
            except Exception:
                result.failed += 1
        except TelegramForbiddenError:
            # User blocked / deactivated the bot.
            result.blocked += 1
            await repo.set_user_active(user_id, False)
        except TelegramBadRequest:
            result.failed += 1
        except Exception as exc:  # noqa: BLE001 — keep the broadcast going
            logger.warning("Broadcast to %s failed: %s", user_id, exc)
            result.failed += 1

        await asyncio.sleep(_DELAY)

    return result
