"""Generate randomized book-store test data and load it into the database.

Nothing here is hardcoded per-store: stores are composed from word pools and
scattered around a configurable centre point, so every run gives fresh data.

Usage:
    python -m scripts.seed              # insert SEED_COUNT (default 15) stores
    python -m scripts.seed 30           # insert 30 stores
    python -m scripts.seed 30 --reset   # wipe the table first, then insert 30

Configurable via environment variables:
    SEED_COUNT       how many stores to generate (default 15)
    SEED_CENTER_LAT  centre latitude  to scatter around (default 41.311081)
    SEED_CENTER_LON  centre longitude to scatter around (default 69.279716)
    SEED_RADIUS_KM   scatter radius in kilometres        (default 12)
"""

import asyncio
import math
import os
import random
import sys

from sqlalchemy import func, select, text

from bot.database import engine, session_factory
from bot.models import Base, Store

# --- word pools the generator composes names/addresses/etc. from ------------

NAME_PREFIXES = [
    "Kitob", "Ilm", "Ziyo", "Ma'rifat", "Bilim", "Sahifa", "Mutolaa",
    "Asar", "Qalam", "Kitobxon", "Hikmat", "Tafakkur",
]
NAME_SUFFIXES = ["do‘koni", "kitob uyi", "kitob olami", "savdo nuqtasi", "markazi"]

DISTRICTS = [
    "Chilonzor", "Yunusobod", "Mirzo Ulug‘bek", "Yakkasaroy", "Shayxontohur",
    "Olmazor", "Uchtepa", "Sergeli", "Bektemir", "Yashnobod", "Mirobod",
    "Yangihayot",
]
STREETS = [
    "Amir Temur shoh ko‘chasi", "Bunyodkor shoh ko‘chasi", "Mustaqillik ko‘chasi",
    "Navoiy ko‘chasi", "Bobur ko‘chasi", "Shota Rustaveli ko‘chasi",
    "Farobiy ko‘chasi", "Qatortol ko‘chasi", "Beruniy ko‘chasi",
]
WORKING_HOURS = [
    "Dush–Yak 09:00–21:00", "Dush–Shan 10:00–20:00", "Dush–Yak 09:00–22:00",
    "Har kuni 08:00–20:00", "Dush–Juma 09:00–18:00", "Dush–Yak 10:00–23:00",
]
DESCRIPTIONS = [
    "To‘liq katalog va qahva burchagi mavjud.",
    "Bolalar va o‘quv adabiyotlari ko‘p.",
    "Savdo markazida, qulay joylashuv.",
    "Metro yonidagi ixcham do‘kon.",
    "Ilmiy adabiyotlar va chet tili javoni.",
    "Buyurtmani olib ketish mumkin.",
    "Badiiy va diniy adabiyotlar keng.",
    "Talabalar uchun chegirmalar mavjud.",
]
PHONE_CODES = ["90", "91", "93", "94", "95", "97", "98", "99", "71"]


def _random_phone() -> str:
    code = random.choice(PHONE_CODES)
    return f"+998 {code} {random.randint(100, 999)}-{random.randint(10, 99)}-{random.randint(10, 99)}"


def _random_point(center_lat: float, center_lon: float, radius_km: float) -> tuple[float, float]:
    """A uniformly random point within `radius_km` of the centre."""
    # Random distance (sqrt for uniform area distribution) and bearing.
    distance_km = radius_km * math.sqrt(random.random())
    bearing = random.uniform(0, 2 * math.pi)
    delta_lat = (distance_km / 111.0) * math.cos(bearing)
    delta_lon = (distance_km / (111.0 * math.cos(math.radians(center_lat)))) * math.sin(bearing)
    return round(center_lat + delta_lat, 6), round(center_lon + delta_lon, 6)


def generate_stores(count: int, center_lat: float, center_lon: float, radius_km: float) -> list[Store]:
    stores: list[Store] = []
    for _ in range(count):
        district = random.choice(DISTRICTS)
        lat, lon = _random_point(center_lat, center_lon, radius_km)
        name = f"{random.choice(NAME_PREFIXES)} {random.choice(NAME_SUFFIXES)} — {district}"
        address = f"{random.choice(STREETS)} {random.randint(1, 199)}, {district}, Toshkent"
        stores.append(
            Store(
                name=name,
                address=address,
                phone=_random_phone(),
                working_hours=random.choice(WORKING_HOURS),
                description=random.choice(DESCRIPTIONS),
                latitude=lat,
                longitude=lon,
            )
        )
    return stores


async def seed(count: int, reset: bool) -> None:
    center_lat = float(os.getenv("SEED_CENTER_LAT", "41.311081"))
    center_lon = float(os.getenv("SEED_CENTER_LON", "69.279716"))
    radius_km = float(os.getenv("SEED_RADIUS_KM", "12"))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        if reset:
            # RESTART IDENTITY so generated test rows start back at id = 1.
            await session.execute(text("TRUNCATE stores RESTART IDENTITY"))
            await session.commit()

        stores = generate_stores(count, center_lat, center_lon, radius_km)
        session.add_all(stores)
        await session.commit()

        total = await session.scalar(select(func.count()).select_from(Store))
        print(f"Inserted {len(stores)} random stores. Total in DB: {total}.")

    await engine.dispose()


def _parse_args() -> tuple[int, bool]:
    args = sys.argv[1:]
    reset = "--reset" in args
    positional = [a for a in args if not a.startswith("--")]
    count = int(positional[0]) if positional else int(os.getenv("SEED_COUNT", "15"))
    return count, reset


if __name__ == "__main__":
    count, reset = _parse_args()
    asyncio.run(seed(count, reset))
