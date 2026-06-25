from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from bot import repository as repo


class RegisterUserMiddleware(BaseMiddleware):
    """Records every (non-bot) user who interacts, for the broadcast audience.

    An in-memory cache avoids re-writing the same user on every single update;
    the DB row is refreshed once per process lifetime per user.
    """

    def __init__(self) -> None:
        self._seen: set[int] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user and not user.is_bot and user.id not in self._seen:
            self._seen.add(user.id)
            await repo.upsert_user(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                language_code=user.language_code,
            )
        return await handler(event, data)
