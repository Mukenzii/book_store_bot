"""In-memory cache of dynamically-added admin ids.

The IsAdmin filter runs on every admin-router update, so we keep the DB-backed
admins in memory instead of querying Postgres each time. The cache is loaded
once at startup and kept in sync whenever an admin is added/removed.
"""

from bot import repository as repo
from bot.config import settings

_db_admins: set[int] = set()


async def load() -> None:
    global _db_admins
    _db_admins = await repo.get_admin_ids()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_id_set or user_id in _db_admins


def is_primary_admin(user_id: int) -> bool:
    """Env-configured admins can't be removed through the bot."""
    return user_id in settings.admin_id_set


def all_admin_ids() -> set[int]:
    return settings.admin_id_set | _db_admins


async def add(user_id: int, added_by: int | None) -> bool:
    added = await repo.add_admin(user_id, added_by)
    if added:
        _db_admins.add(user_id)
    return added


async def remove(user_id: int) -> bool:
    removed = await repo.remove_admin(user_id)
    if removed:
        _db_admins.discard(user_id)
    return removed
