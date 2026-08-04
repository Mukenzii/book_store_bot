import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from bot import repository as repo

# How often (seconds) we re-write a known user's last_seen. Short enough that
# the "active in the last N minutes" stats stay accurate, long enough that a
# burst of taps doesn't hammer the DB.
_TOUCH_THROTTLE = 60.0


class RegisterUserMiddleware(BaseMiddleware):
    """Records every (non-bot) user who interacts, and keeps last_seen fresh.

    First interaction upserts the full row. After that we only bump last_seen,
    and throttle even that to at most once per `_TOUCH_THROTTLE` seconds per
    user so a flurry of button taps doesn't turn into a flurry of writes.
    """

    def __init__(self) -> None:
        # user_id -> monotonic timestamp of our last DB write for them
        self._last_write: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user and not user.is_bot:
            now = time.monotonic()
            last = self._last_write.get(user.id)
            if last is None:
                # Never seen this process lifetime — full upsert (also sets last_seen).
                self._last_write[user.id] = now
                await repo.upsert_user(
                    user_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    language_code=user.language_code,
                )
            elif now - last >= _TOUCH_THROTTLE:
                self._last_write[user.id] = now
                await repo.touch_user(user.id)
        return await handler(event, data)
