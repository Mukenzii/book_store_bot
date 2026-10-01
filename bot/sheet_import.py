"""Import stores from the configured Google Sheet (SHEET_URL) into the DB.

The active sheet has one row per store with SEPARATE latitude/longitude columns
(comma as the decimal separator), not map links:

    id | name | phone | agent | region | lat | lon | ...

Nameless rows fall back to "Kitob do'koni". Duplicate-checking skips a row that
matches an existing store — or an earlier row in the same sheet — by location
(~1 m) or by a distinct (non-generic) name, so the button is safe to re-tap.
"""

import asyncio
import csv
import io
import re
import urllib.request
from dataclasses import dataclass

from sqlalchemy import select

from bot.config import settings
from bot.database import session_factory
from bot.models import Store
from scripts.import_sheet import _norm_phone, _valid_uz

# Names too generic to dedupe on (every nameless row falls back to this).
_GENERIC_NAMES = {"kitobdokoni", "kitobdukoni"}


@dataclass
class ImportSummary:
    total_rows: int
    added: int
    duplicates: int
    no_location: int


def _fetch_rows() -> list[list[str]]:
    req = urllib.request.Request(
        settings.sheet_csv_url, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    return list(csv.reader(io.StringIO(raw)))


def _num(value: str) -> float | None:
    # Sheet uses "41,2780" (comma decimal). Also tolerate a plain "41.2780".
    value = (value or "").strip().replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def _build_stores(rows: list[list[str]]) -> tuple[list[Store], int]:
    """Parse rows into Store objects; count rows without usable coordinates.

    A row whose lat/lon don't parse (blank rows, a header row, bad data) is
    counted as skipped — so we don't need to know whether the sheet has a header.
    """
    stores: list[Store] = []
    skipped = 0
    for row in rows:
        cells = [c.strip() for c in (row + [""] * 7)[:7]]
        _id, name, phone, agent, region, lat_s, lon_s = cells
        lat, lon = _num(lat_s), _num(lon_s)
        if lat is None or lon is None or not _valid_uz(lat, lon):
            skipped += 1
            continue
        stores.append(
            Store(
                name=(name or "Kitob do‘koni")[:255],
                address=region or None,
                phone=_norm_phone(phone),
                working_hours=None,
                # The sheet's agent column is internal — never shown to customers.
                description=None,
                latitude=round(lat, 6),
                longitude=round(lon, 6),
            )
        )
    return stores, skipped


def _name_key(name: str | None) -> str | None:
    key = re.sub(r"[^a-z0-9а-я]", "", (name or "").lower())
    return None if not key or key in _GENERIC_NAMES else key


def _coord_key(lat: float, lon: float) -> tuple[float, float]:
    # ~1 m precision — identical pins collapse, distinct nearby shops stay apart.
    return (round(lat, 5), round(lon, 5))


async def run_import() -> ImportSummary:
    """Fetch the sheet, skip duplicates, insert the genuinely new stores."""
    rows = await asyncio.to_thread(_fetch_rows)  # network — keep off the loop
    parsed, no_location = _build_stores(rows)

    async with session_factory() as session:
        existing = (await session.scalars(select(Store))).all()
        seen_coords = {_coord_key(s.latitude, s.longitude) for s in existing}
        seen_names = {k for s in existing if (k := _name_key(s.name))}

        to_add: list[Store] = []
        duplicates = 0
        for store in parsed:
            ckey = _coord_key(store.latitude, store.longitude)
            nkey = _name_key(store.name)
            if ckey in seen_coords or (nkey and nkey in seen_names):
                duplicates += 1
                continue
            seen_coords.add(ckey)
            if nkey:
                seen_names.add(nkey)
            to_add.append(store)

        session.add_all(to_add)
        await session.commit()

    return ImportSummary(
        total_rows=len(rows),
        added=len(to_add),
        duplicates=duplicates,
        no_location=no_location,
    )
