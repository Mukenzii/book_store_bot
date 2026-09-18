import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update, User

from bot import repository as repo


# Ignore a repeat of the SAME request from the SAME user within this window.
_THROTTLE_INTERVAL = 1.5


class ThrottleMiddleware(BaseMiddleware):
    """Collapse rapid duplicate requests so the bot answers each only once.

    If a user fires the same message or taps the same button again within
    `interval` seconds, the repeat is ignored. This stops double-taps and the
    repeated «/start» bursts — which, on a slow link, all arrive together after
    a reconnect and would otherwise each get their own reply. Distinct actions
    are never dropped; only identical, back-to-back repeats.
    """

    def __init__(self, interval: float = _THROTTLE_INTERVAL) -> None:
        self.interval = interval
        # (user_id, request signature) -> monotonic time we last handled it.
        self._last: dict[tuple[int, str], float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        inner = getattr(event, "event", None) if isinstance(event, Update) else event
        sig: str | None = None
        if isinstance(inner, Message):
            sig = f"m:{inner.text or inner.caption or inner.content_type}"
        elif isinstance(inner, CallbackQuery):
            sig = f"c:{inner.data}"

        if user is not None and sig is not None:
            now = time.monotonic()
            key = (user.id, sig)
            if now - self._last.get(key, 0.0) < self.interval:
                # A duplicate within the window — acknowledge a button so its
                # spinner stops, then drop it (no handler, no reply).
                if isinstance(inner, CallbackQuery):
                    try:
                        await inner.answer()
                    except Exception:  # noqa: BLE001 — best-effort ack
                        pass
                return None
            self._last[key] = now
            if len(self._last) > 10_000:  # keep memory bounded over time
                cutoff = now - self.interval
                self._last = {k: v for k, v in self._last.items() if v > cutoff}

        return await handler(event, data)

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
