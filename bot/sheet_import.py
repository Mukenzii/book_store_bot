"""Import stores from the configured Google Sheet into the DB, on demand.

Reuses the sheet parser from ``scripts.import_sheet`` (columns + coordinate
extraction, and the "Kitob do'koni" fallback name) and adds duplicate-checking:
a row is skipped when it matches an existing store — or an earlier row in the
same sheet — by location, or by a distinct (non-generic) name. So the admin can
tap the button repeatedly and never create duplicates.
"""

import asyncio
import re
from dataclasses import dataclass

from sqlalchemy import select

from bot.database import session_factory
from bot.models import Store
from scripts.import_sheet import build_stores, fetch_rows

# Names too generic to dedupe on (every nameless row falls back to this, so two
# different shops both called "Kitob do'koni" must NOT count as duplicates).
_GENERIC_NAMES = {"kitobdokoni", "kitobdukoni"}


@dataclass
class ImportSummary:
    total_rows: int
    added: int
    duplicates: int
    no_location: int


def _name_key(name: str | None) -> str | None:
    key = re.sub(r"[^a-z0-9а-я]", "", (name or "").lower())
    return None if not key or key in _GENERIC_NAMES else key


def _coord_key(lat: float, lon: float) -> tuple[float, float]:
    # ~1 m precision — identical pins (copy-pasted rows) collapse, distinct
    # nearby shops stay separate.
    return (round(lat, 5), round(lon, 5))


async def run_import() -> ImportSummary:
    """Fetch the sheet, skip duplicates, insert the genuinely new stores."""
    # fetch + link-resolution are blocking (network) — keep them off the loop.
    rows = await asyncio.to_thread(fetch_rows)
    parsed, no_location = await asyncio.to_thread(build_stores, rows)

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
