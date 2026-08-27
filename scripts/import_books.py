"""Migrate Falaq Nashr's catalogue AND publishing-house info into the database.

Two data sets are seeded (so a fresh production DB gets everything in one run):

1. Books — replaces whatever is in the ``books`` table (any sample/old data)
   with the real titles in ``scripts/books_seed.json`` — the 54 active books
   across Falaq Nashr's imprints (Nun nashr, Falaq nashr, Eng sharafli ummat,
   Holis nashr, G‘iyosiddin Habibulloh). Prices are intentionally omitted — the
   AI assistant never quotes prices to customers. Each entry may carry an
   ``image`` filename that must exist under ``book_images/``.

2. Publishing-house info — the AI's "Nashriyot haqida" text, from
   ``scripts/house_info.txt``, written to the ``settings`` table under the same
   key the assistant/admin panel use. Only seeded when it is NOT already set, so
   an admin's own edit (via 📖 Kitoblar → 🏛 Nashriyot haqida) is never clobbered
   on a later deploy. To force the seed text back in, clear the row first.

Usage (inside the container, which has DB access):
    python -m scripts.import_books
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import text

from bot.ai import HOUSE_INFO_KEY
from bot.database import engine, session_factory
from bot.models import Base, Book

SEED_PATH = Path(__file__).resolve().parent / "books_seed.json"
HOUSE_INFO_PATH = Path(__file__).resolve().parent / "house_info.txt"

# Book columns we allow the seed file to set.
_FIELDS = {
    "title", "author", "publisher", "genre", "annotation",
    "language", "age_group", "isbn", "year", "pages", "tags", "image",
}


def _load_seed() -> list[dict]:
    with SEED_PATH.open(encoding="utf-8") as f:
        rows = json.load(f)
    books: list[dict] = []
    for r in rows:
        b = {k: v for k, v in r.items() if k in _FIELDS and v not in (None, "")}
        if not b.get("title"):
            continue
        books.append(b)
    return books


def _load_house_info() -> str:
    if not HOUSE_INFO_PATH.exists():
        return ""
    return HOUSE_INFO_PATH.read_text(encoding="utf-8").strip()


async def main() -> None:
    books = _load_seed()
    house_info = _load_house_info()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all never ALTERs an existing table — make sure newer columns
        # exist on catalogues created before they were added.
        await conn.execute(
            text("ALTER TABLE books ADD COLUMN IF NOT EXISTS image VARCHAR(255)")
        )
        await conn.execute(
            text("ALTER TABLE books ADD COLUMN IF NOT EXISTS publisher VARCHAR(120)")
        )
        # Remove whatever is there now (old catalogue) before loading the real books.
        await conn.execute(text("DELETE FROM books"))

        # Seed the publishing-house info — but only if the admin hasn't set it,
        # so a later deploy never overwrites their own "Nashriyot haqida" text.
        house_seeded = False
        if house_info:
            res = await conn.execute(
                text(
                    "INSERT INTO settings (key, value) VALUES (:k, :v) "
                    "ON CONFLICT (key) DO NOTHING"
                ),
                {"k": HOUSE_INFO_KEY, "v": house_info},
            )
            house_seeded = bool(res.rowcount)

    async with session_factory() as session:
        session.add_all([Book(**b) for b in books])
        await session.commit()

    await engine.dispose()

    with_img = sum(1 for b in books if b.get("image"))
    print(f"Imported {len(books)} real books (old catalogue removed).")
    print(f"  {with_img} have a cover image, {len(books) - with_img} do not.")
    if not house_info:
        print("Publishing-house info: skipped (scripts/house_info.txt missing).")
    elif house_seeded:
        print("Publishing-house info: seeded into settings.")
    else:
        print("Publishing-house info: already set — left the existing value untouched.")


if __name__ == "__main__":
    asyncio.run(main())
