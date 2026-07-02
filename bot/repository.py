from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

from bot.database import session_factory
from bot.models import ScheduledPost, Setting, Store, User


@dataclass(slots=True)
class StoreWithDistance:
    """A store row enriched with its distance from the user's location."""

    id: int
    name: str
    address: str
    phone: str | None
    working_hours: str | None
    description: str | None
    latitude: float
    longitude: float
    distance_km: float


# Great-circle distance via the haversine formula, computed in SQL so we can
# order/limit on the database side. Works on vanilla PostgreSQL (no PostGIS).
_NEAREST_SQL = text(
    """
    SELECT
        id, name, address, phone, working_hours, description,
        latitude, longitude,
        (6371 * acos(
            LEAST(1.0, GREATEST(-1.0,
                cos(radians(:lat)) * cos(radians(latitude)) *
                cos(radians(longitude) - radians(:lon)) +
                sin(radians(:lat)) * sin(radians(latitude))
            ))
        )) AS distance_km
    FROM stores
    ORDER BY distance_km ASC
    LIMIT :limit
    """
)

_BY_ID_SQL = text(
    """
    SELECT
        id, name, address, phone, working_hours, description,
        latitude, longitude,
        (6371 * acos(
            LEAST(1.0, GREATEST(-1.0,
                cos(radians(:lat)) * cos(radians(latitude)) *
                cos(radians(longitude) - radians(:lon)) +
                sin(radians(:lat)) * sin(radians(latitude))
            ))
        )) AS distance_km
    FROM stores
    WHERE id = :store_id
    """
)


def _row_to_store(row) -> StoreWithDistance:
    return StoreWithDistance(
        id=row.id,
        name=row.name,
        address=row.address,
        phone=row.phone,
        working_hours=row.working_hours,
        description=row.description,
        latitude=row.latitude,
        longitude=row.longitude,
        distance_km=float(row.distance_km),
    )


async def find_nearest_stores(lat: float, lon: float, limit: int) -> list[StoreWithDistance]:
    async with session_factory() as session:
        result = await session.execute(_NEAREST_SQL, {"lat": lat, "lon": lon, "limit": limit})
        return [_row_to_store(row) for row in result]


async def get_store(store_id: int, lat: float, lon: float) -> StoreWithDistance | None:
    async with session_factory() as session:
        result = await session.execute(
            _BY_ID_SQL, {"store_id": store_id, "lat": lat, "lon": lon}
        )
        row = result.first()
        return _row_to_store(row) if row else None


# --- admin CRUD (operate on the ORM model directly, no distance) -------------

async def count_stores() -> int:
    from sqlalchemy import func, select

    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(Store)) or 0


async def list_stores(limit: int, offset: int) -> list[Store]:
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.scalars(
            select(Store).order_by(Store.id).limit(limit).offset(offset)
        )
        return list(result)


async def get_store_by_id(store_id: int) -> Store | None:
    async with session_factory() as session:
        return await session.get(Store, store_id)


async def create_store(**fields) -> Store:
    async with session_factory() as session:
        store = Store(**fields)
        session.add(store)
        await session.commit()
        await session.refresh(store)
        return store


async def update_store(store_id: int, **fields) -> Store | None:
    async with session_factory() as session:
        store = await session.get(Store, store_id)
        if store is None:
            return None
        for key, value in fields.items():
            setattr(store, key, value)
        await session.commit()
        await session.refresh(store)
        return store


async def delete_store(store_id: int) -> bool:
    async with session_factory() as session:
        store = await session.get(Store, store_id)
        if store is None:
            return False
        await session.delete(store)
        await session.commit()
        return True


# --- users (broadcast audience) ---------------------------------------------

async def upsert_user(
    user_id: int,
    username: str | None,
    first_name: str | None,
    language_code: str | None,
) -> None:
    """Insert the user, or refresh their details and re-activate on conflict."""
    from sqlalchemy.dialects.postgresql import insert

    stmt = insert(User).values(
        id=user_id,
        username=username,
        first_name=first_name,
        language_code=language_code,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[User.id],
        set_={
            "username": stmt.excluded.username,
            "first_name": stmt.excluded.first_name,
            "language_code": stmt.excluded.language_code,
            "is_active": True,
        },
    )
    async with session_factory() as session:
        await session.execute(stmt)
        await session.commit()


async def set_user_active(user_id: int, active: bool) -> None:
    async with session_factory() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.is_active = active
            await session.commit()


async def active_user_ids() -> list[int]:
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.scalars(select(User.id).where(User.is_active.is_(True)))
        return list(result)


async def count_users() -> tuple[int, int]:
    """Return (total_users, active_users)."""
    from sqlalchemy import func, select

    async with session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(User)) or 0
        active = await session.scalar(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        ) or 0
        return total, active


# --- weekly schedule: enabled days + scheduled posts -------------------------

_SCHEDULE_DAYS_KEY = "schedule_weekdays"


async def get_enabled_weekdays() -> set[int]:
    async with session_factory() as session:
        setting = await session.get(Setting, _SCHEDULE_DAYS_KEY)
        if not setting or not setting.value:
            return set()
        return {int(x) for x in setting.value.split(",") if x.strip().isdigit()}


async def set_enabled_weekdays(days: set[int]) -> None:
    value = ",".join(str(d) for d in sorted(days))
    async with session_factory() as session:
        setting = await session.get(Setting, _SCHEDULE_DAYS_KEY)
        if setting is None:
            session.add(Setting(key=_SCHEDULE_DAYS_KEY, value=value))
        else:
            setting.value = value
        await session.commit()


async def toggle_weekday(day: int) -> set[int]:
    days = await get_enabled_weekdays()
    days.discard(day) if day in days else days.add(day)
    await set_enabled_weekdays(days)
    return days


async def create_scheduled_post(
    weekday: int, send_time: str, from_chat_id: int, message_id: int, preview: str
) -> ScheduledPost:
    async with session_factory() as session:
        post = ScheduledPost(
            weekday=weekday,
            send_time=send_time,
            from_chat_id=from_chat_id,
            message_id=message_id,
            preview=preview[:120],
        )
        session.add(post)
        await session.commit()
        await session.refresh(post)
        return post


async def list_scheduled_posts() -> list[ScheduledPost]:
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.scalars(
            select(ScheduledPost).order_by(ScheduledPost.weekday, ScheduledPost.send_time)
        )
        return list(result)


async def get_scheduled_post(post_id: int) -> ScheduledPost | None:
    async with session_factory() as session:
        return await session.get(ScheduledPost, post_id)


async def delete_scheduled_post(post_id: int) -> bool:
    async with session_factory() as session:
        post = await session.get(ScheduledPost, post_id)
        if post is None:
            return False
        await session.delete(post)
        await session.commit()
        return True


async def count_scheduled_posts() -> int:
    from sqlalchemy import func, select

    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(ScheduledPost)) or 0


async def due_scheduled_posts(weekday: int, hhmm: str, today: date) -> list[ScheduledPost]:
    """Active posts for this weekday whose time has arrived and weren't sent today."""
    from sqlalchemy import or_, select

    async with session_factory() as session:
        result = await session.scalars(
            select(ScheduledPost).where(
                ScheduledPost.is_active.is_(True),
                ScheduledPost.weekday == weekday,
                ScheduledPost.send_time <= hhmm,
                or_(
                    ScheduledPost.last_sent_on.is_(None),
                    ScheduledPost.last_sent_on != today,
                ),
            )
        )
        return list(result)


async def mark_post_sent(post_id: int, sent_on: date) -> None:
    async with session_factory() as session:
        post = await session.get(ScheduledPost, post_id)
        if post is not None:
            post.last_sent_on = sent_on
            await session.commit()
