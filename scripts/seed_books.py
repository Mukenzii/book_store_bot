"""Load a few sample books so the AI assistant is testable before real data.

Usage (inside the container, which has DB access):
    python -m scripts.seed_books            # add samples
    python -m scripts.seed_books --reset    # wipe the books table first
"""

import asyncio
import sys

from sqlalchemy import text

from bot.database import engine, session_factory
from bot.models import Base, Book

SAMPLE_BOOKS = [
    dict(title="O‘tkan kunlar", author="Abdulla Qodiriy", genre="badiiy / roman",
         price="52 000 so‘m", language="o‘zbek", year=1926,
         tags="klassika, tarixiy, sevgi, o‘zbek adabiyoti",
         annotation="O‘zbek adabiyotining birinchi romani. Otabek va Kumushning "
                    "fojiali sevgisi orqali XIX asr Turkiston hayoti tasvirlangan."),
    dict(title="Mehrobdan chayon", author="Abdulla Qodiriy", genre="badiiy / roman",
         price="48 000 so‘m", language="o‘zbek", year=1929,
         tags="klassika, tarixiy, saroy, o‘zbek adabiyoti",
         annotation="Xudoyorxon saroyidagi fitna va muhabbat haqidagi tarixiy roman."),
    dict(title="Kichkina shahzoda", author="Antuan de Sent-Ekzyuperi",
         genre="bolalar / falsafiy", price="39 000 so‘m", language="o‘zbek",
         age_group="6+", tags="bolalar, ertak, falsafa, do‘stlik",
         annotation="Sayyoralar bo‘ylab sayohat qilgan kichkina shahzoda haqidagi "
                    "mashhur ertak — kattalar uchun ham chuqur ma’noli."),
    dict(title="Alkimyogar", author="Paulo Koelo", genre="badiiy / falsafiy",
         price="55 000 so‘m", language="o‘zbek",
         tags="motivatsiya, sayohat, orzu, falsafa",
         annotation="O‘z afsonasini izlab yo‘lga chiqqan cho‘pon Santyago haqidagi "
                    "ilhomlantiruvchi roman."),
    dict(title="Sherlok Holms sarguzashtlari", author="Artur Konan Doyl",
         genre="detektiv", price="61 000 so‘m", language="o‘zbek",
         tags="detektiv, jinoyat, sirli, mantiq",
         annotation="Mashhur syshchik Sherlok Holmsning eng qiziqarli ishlaridan "
                    "iborat hikoyalar to‘plami."),
    dict(title="Matematika olamiga sayohat", author="Falaq Nashr jamoasi",
         genre="bolalar / ta’limiy", price="34 000 so‘m", language="o‘zbek",
         age_group="8+", tags="ta’lim, matematika, bolalar, rivojlantiruvchi",
         annotation="Bolalar uchun matematikani o‘yin tarzida o‘rgatuvchi rangli kitob.",
         in_stock=False),
]


async def main(reset: bool) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if reset:
            await conn.execute(text("DELETE FROM books"))

    async with session_factory() as session:
        session.add_all([Book(**b) for b in SAMPLE_BOOKS])
        await session.commit()

    await engine.dispose()
    print(f"Seeded {len(SAMPLE_BOOKS)} books (reset={reset}).")


if __name__ == "__main__":
    asyncio.run(main(reset="--reset" in sys.argv))
