from dataclasses import dataclass

from sqlalchemy import text

from bot.database import session_factory
from bot.models import Store, User


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
