from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from bot import admins


class IsAdmin(BaseFilter):
    """Passes for env ADMIN_IDS plus admins added through the bot."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        return bool(user and admins.is_admin(user.id))
