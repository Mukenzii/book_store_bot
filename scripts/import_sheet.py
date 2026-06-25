"""Import real book stores from the public Google Sheet into the database.

Sheet columns: Agent | contact | type | Do'kon nomi | hours | phone | Lokatsiya
The "Lokatsiya" cell is a map link; we extract coordinates from the many link
formats Google/Yandex produce (q=, @lat,lon, !3d!4d, DMS, /search/) and resolve
short links (maps.app.goo.gl) by following their redirect.

Usage (inside the container, which has DB access + internet):
    python -m scripts.import_sheet            # add imported rows
    python -m scripts.import_sheet --reset    # wipe table first, then import

Rows whose location has no resolvable coordinates (pasted text addresses,
Yandex org links) are skipped and reported.
"""

import asyncio
import csv
import io
import re
import sys
import urllib.parse
import urllib.request

from sqlalchemy import text

from bot.config import settings
from bot.database import engine, session_factory
from bot.models import Base, Store

_DMS = re.compile(r'(\d+)°(\d+)\'([\d.]+)"([NS]).{0,4}?(\d+)°(\d+)\'([\d.]+)"([EW])')


def _dms(d: str, m: str, s: str, hemi: str) -> float:
    v = float(d) + float(m) / 60 + float(s) / 3600
    return -v if hemi in ("S", "W") else v


def extract_coords(url: str) -> tuple[float, float] | None:
    """Pull (lat, lon) out of any of the map-link formats we've seen."""
    if not url:
        return None
    u = urllib.parse.unquote(url)
    m = re.search(r'[?&](?:q|ll)=(-?\d+\.\d+),\s*(-?\d+\.\d+)', u)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', u)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r'/search/(-?\d+\.\d+),\s*\+?(-?\d+\.\d+)', u)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = _DMS.search(u)
    if m:
        return _dms(*m.group(1, 2, 3, 4)), _dms(*m.group(5, 6, 7, 8))
    m = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', u)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def _resolve(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.geturl()
    except Exception:
        return url


def _coords_from_cell(loc: str) -> tuple[float, float] | None:
    coords = extract_coords(loc)
    if coords:
        return coords
    if "goo.gl" in loc or "maps.app" in loc or "yandex" in loc:
        return extract_coords(_resolve(loc))
    return None


def _norm_phone(raw: str) -> str | None:
    if not raw:
        return None
    out = []
    for token in re.split(r"[\s,/]+", raw.strip()):
        digits = re.sub(r"\D", "", token)
        if len(digits) == 9:
            out.append("+998" + digits)
        elif len(digits) == 12 and digits.startswith("998"):
            out.append("+" + digits)
        elif digits:
            out.append(token)
    return ", ".join(out) or None


def _valid_uz(lat: float, lon: float) -> bool:
    # Rough Uzbekistan bounding box — drops obviously-broken coordinates.
    return 37.0 <= lat <= 46.0 and 55.0 <= lon <= 74.0


def fetch_rows() -> list[list[str]]:
    req = urllib.request.Request(settings.sheet_csv_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    return list(csv.reader(io.StringIO(raw)))[1:]  # skip header


def build_stores(rows: list[list[str]]) -> tuple[list[Store], int]:
    stores: list[Store] = []
    skipped = 0
    for row in rows:
        row = (row + [""] * 7)[:7]
        _agent, _contact, typ, name, hours, phone, loc = (c.strip() for c in row)
        coords = _coords_from_cell(loc)
        if not coords or not _valid_uz(*coords):
            skipped += 1
            continue
        lat, lon = coords
        store_name = name or typ or "Kitob do‘koni"
        description = typ if typ and typ != store_name else None
        stores.append(
            Store(
                name=store_name[:255],
                address=None,
                phone=_norm_phone(phone),
                working_hours=(hours or None),
                description=description,
                latitude=round(lat, 6),
                longitude=round(lon, 6),
            )
        )
    return stores, skipped


async def main(reset: bool) -> None:
    print(f"Fetching: {settings.sheet_csv_url}")
    rows = fetch_rows()
    stores, skipped = build_stores(rows)
    print(f"Parsed {len(rows)} rows -> {len(stores)} stores with coordinates, {skipped} skipped.")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        if reset:
            await session.execute(text("TRUNCATE stores RESTART IDENTITY"))
        session.add_all(stores)
        await session.commit()

    print(f"Imported {len(stores)} stores. (reset={reset})")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(reset="--reset" in sys.argv[1:]))
