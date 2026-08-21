"""Load Falaq Nashr's real books into the catalogue.

Replaces whatever is in the `books` table (removing any sample/fake data) with
the real titles below. Data was extracted from the publishing house's book
template documents. Prices are intentionally omitted (the AI never quotes
prices to customers).

Usage (inside the container, which has DB access):
    python -m scripts.import_books
"""

import asyncio
import re

from sqlalchemy import text

from bot.database import engine, session_factory
from bot.models import Base, Book


def _slug(title: str) -> str:
    """Deterministic filename slug for a book's image (book_images/<slug>.jpg)."""
    t = title.lower().replace("’", "").replace("‘", "").replace("'", "")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t

BOOKS = [
    dict(
        title="Qulog‘im senda, qizim!",
        author="Abdulloh Muhammad Abdulmut’iy",
        genre="motivatsiya, diniy, ilmiy-ommabop, ta’lim",
        pages=399, language="ravon", age_group="qizlar, ota-onalar",
        tags="qizlar, tarbiya, odob, diniy, nasihat",
        annotation="Qizlarning ruhiy olami, tarbiyasi va odob-axloqiga bag‘ishlangan "
                   "diniy-ma’rifiy kitob. Oyat, hadis va hayotiy misollar orqali qizlarga "
                   "o‘z qadrini bilish, sabr va hayoni o‘rgatadi; ota-onalar uchun ham foydali.",
    ),
    dict(
        title="Yusufning qizi",
        author="Josim Umron",
        genre="roman, hayotiy",
        pages=181, language="ravon, badiiy",
        tags="roman, muhabbat, hayotiy, badiiy",
        annotation="Yusuf va Nur o‘rtasidagi beg‘ubor muhabbat va undan keyingi hayotiy "
                   "sinovlar tasvirlangan, hayotiy voqealarga asoslangan roman.",
    ),
    dict(
        title="Til sayqali",
        author="Saloh Muhammad Abul Hoj",
        genre="diniy, ilmiy-ommabop",
        pages=465, language="ravon, ilmiy",
        tags="til odobi, axloq, diniy, so‘z",
        annotation="Til odobi haqidagi kitob: insonni yomon so‘zlardan poklab, tilni "
                   "to‘g‘ri va savobli so‘zlarga yo‘naltirishga o‘rgatadi.",
    ),
    dict(
        title="Binafsha shu’lasi (2-qism)",
        author="Usoma Muslim",
        genre="roman, fantastika, ilmiy-ommabop, ta’lim",
        language="badiiy",
        tags="fantastika, roman, sarguzasht",
        annotation="Fantastik roman. Qishloqdagi Yoziy ismli yigit atrofida boshlanuvchi, "
                   "«binafsha shu’lasi» ramzi orqali boshqa olamga yo‘l ochiladigan asarning "
                   "ikkinchi qismi.",
    ),
    dict(
        title="Boy bo‘lishni istasangiz",
        author="Islom Jamol",
        genre="motivatsiya, diniy, ilmiy-ommabop, psixologiya, biznes, ta’lim",
        pages=295, language="ravon, ilmiy",
        tags="motivatsiya, boylik, biznes, muvaffaqiyat, mehnat",
        annotation="Boylik va muvaffaqiyatga to‘g‘ri qarashga undovchi motivatsion kitob. "
                   "Mehnatsevarlik, to‘g‘ri fikrlash va halollik orqali hayotni yaxshilashga "
                   "chorlaydi; yoshlar va tadbirkorlar uchun.",
    ),
    dict(
        title="La’natlangan qiz",
        author=None,
        genre="fantastik, roman",
        pages=232, language="ravon",
        tags="fantastika, roman, adolat, sinov",
        annotation="Malika Shamsizamon taqdiri haqidagi fantastik roman. Qiz farzandga "
                   "nisbatan adolatsiz qarashlar, zo‘ravonlik va begunohni ayblash kabi "
                   "illatlar badiiy tasvirlangan.",
    ),
    dict(
        title="Ayriliqdan bir qadam oldin",
        author="Ahmad Medhat",
        genre="psixologiya, badiiy",
        language="ravon, badiiy",
        tags="psixologiya, oila, sevgi, kechirim, badiiy",
        annotation="Ali va Samoning oilaviy hayoti, tushunmovchiliklar va ayriliq yoqasidagi "
                   "kechinmalar haqidagi psixologik-badiiy asar. Sevgi, kechirim va ruhiy "
                   "jarohatlar mavzusida.",
    ),
    dict(
        title="Maxfiy hujjatlar",
        author="Iymon Anaziy va Fotima Hayyot",
        genre="psixologiya, badiiy",
        language="badiiy",
        tags="badiiy, sir, psixologiya, roman",
        annotation="Xolid ismli yigit atrofida boshlanuvchi, qahramonlar sirlari yillar "
                   "davomida saqlangan «maxfiy hujjatlar» orqali ochiladigan badiiy-psixologik asar.",
    ),
    dict(
        title="Yosh yigitga nasihat",
        author="Hasson Shamsiy Posho",
        genre="motivatsiya, diniy, tarixiy, ilmiy-ommabop, psixologiya, ta’lim, sog‘liq",
        pages=301, language="ravon, ilmiy",
        tags="yigitlar, nasihat, diniy, tarbiya, motivatsiya",
        annotation="Yigitlarga (va barchaga) qaratilgan pand-nasihat kitobi. To‘g‘ri yo‘lni "
                   "ko‘rsatuvchi diniy va hayotiy o‘gitlar to‘plami.",
    ),
    dict(
        title="Vasvasa va uni yengish yo‘llari",
        author="Ali ibn Husayn Ali",
        genre="diniy, ilmiy-ommabop",
        pages=159, language="ravon, ilmiy",
        tags="vasvasa, diniy, nafs, ruhiyat",
        annotation="Vasvasaning mohiyati, zararlari va undan qutulish yo‘llari haqidagi "
                   "diniy-ma’rifiy kitob.",
    ),
    dict(
        title="Ruhiy suhbatlar",
        author="Doktor Muhammad Ibrohim",
        genre="motivatsiya, diniy, ilmiy-ommabop, psixologiya, ta’lim, sog‘liq",
        pages=188, language="ravon, ilmiy",
        tags="ruhiyat, psixologiya, salomatlik, motivatsiya",
        annotation="Insonning ruhiy salomatligiga bag‘ishlangan kitob. Hayot yo‘lida "
                   "qo‘llanma bo‘lib, ruhiy muammolarga ko‘rsatma va yechimlar beradi.",
    ),
    dict(
        title="Qaysarlikdan itoatkorlikka",
        author="Doktor Abdulloh Muhammad Mu’ti",
        genre="diniy, ilmiy-ommabop, ta’lim",
        pages=170, language="ravon, ilmiy",
        tags="tarbiya, bolalar, qaysarlik, ota-ona",
        annotation="Farzand tarbiyasi haqidagi kitob: bolalardagi qaysarlikni mehr, sabr va "
                   "to‘g‘ri tarbiya orqali ijobiy yo‘nalishga o‘zgartirish yo‘llarini o‘rgatadi.",
    ),
    dict(
        title="Qur’on qalbiga safar",
        author="Yosin Pishgin",
        genre="roman, diniy, ilmiy-ommabop, ta’lim",
        pages=415, language="ravon, sodda",
        tags="Qur’on, diniy, tafakkur, Yosin surasi",
        annotation="Qur’onni shunchaki o‘qish emas, uni qalban his etib tafakkur bilan "
                   "tilovat qilishga chorlovchi kitob. Yosin surasi tafsiriga alohida "
                   "e’tibor qaratilgan.",
    ),
    dict(
        title="Metin qoyalar",
        author="Hasson Shamsiy Posho",
        genre="motivatsiya, diniy, tarixiy, ilmiy-ommabop",
        pages=375, language="ravon, badiiy",
        tags="motivatsiya, ma’naviyat, tarbiya, diniy",
        annotation="Insonni ma’naviy, xulqiy va ijtimoiy jihatdan yetuk shaxs qilib "
                   "tarbiyalashga qaratilgan kitob. Sinovli hayotda mustahkam turishni "
                   "«metin qoyalar» ramzi orqali tushuntiradi.",
    ),
    dict(
        title="Kelishda non olib keling",
        author="Shermin Yashar",
        genre="hikoya",
        pages=288, language="ravon, sodda, badiiy",
        tags="hikoya, oila, ota, hayotiy",
        annotation="Otaning uzoq yillardan so‘ng uyga qaytishi haqidagi ta’sirli hikoya "
                   "bilan ochiladigan, hayotiy kechinmalarga boy hikoyalar to‘plami.",
    ),
    dict(
        title="Ishonchli xabar",
        author="Adham Sharqoviy",
        genre="hikoya, motivatsiya, diniy, ilmiy-ommabop",
        pages=302, language="ravon, sodda",
        tags="nasihat, diniy, motivatsiya, hikoya",
        annotation="Qalbga yetib boradigan, haqiqatga asoslangan nasihat va xabarlar "
                   "to‘plami. Yomonlikni qoralashdan ko‘ra yaxshilikka chorlashni maqsad qilgan.",
    ),
    dict(
        title="Hayz va nifos hukmlari",
        author="Doktor Saloh Abul Xoj",
        genre="diniy-fiqhiy, ilmiy-ommabop, ta’limiy",
        pages=173, language="ravon, sodda",
        tags="fiqh, ayollar, hayz, nifos, ibodat",
        annotation="Ayollarga oid fiqhiy masalalar — hayz va nifosning ta’rifi, muddati, "
                   "namoz, ro‘za, tavof va boshqa hukmlar — sodda uslubda savol-javob tarzida "
                   "tushuntirilgan.",
    ),
    dict(
        title="Payg‘ambardan maktublar",
        author="Adham Sharqoviy",
        genre="diniy, ma’rifiy",
        pages=432, language="ravon, sodda, badiiy",
        tags="sahobalar, nasihat, diniy, saboq",
        annotation="Saodat asrida sahobalar duch kelgan sinovlar va Rasululloh (s.a.v.) "
                   "ularga bergan nasihatlari badiiy uslubda bayon qilingan; bugungi inson "
                   "uchun hayotiy saboqlar.",
    ),
    dict(
        title="Rosulullohning uylari",
        author="Muhammad ibn Foris al-Jamil",
        genre="diniy",
        pages=103, language="ravon, ilmiy",
        tags="diniy, siyrat, oila, Rasululloh",
        annotation="Payg‘ambarimiz (s.a.v.) xonadonlari, ayniqsa Oisha onamiz uylari "
                   "misolida oilaviy hayoti tasvirlangan diniy kitob.",
    ),
]


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all never ALTERs an existing table — make sure the image column
        # is present on catalogues created before it was added.
        await conn.execute(
            text("ALTER TABLE books ADD COLUMN IF NOT EXISTS image VARCHAR(255)")
        )
        # Remove whatever is there now (sample/fake data) before loading the real books.
        await conn.execute(text("DELETE FROM books"))

    async with session_factory() as session:
        session.add_all([Book(image=f"{_slug(b['title'])}.jpg", **b) for b in BOOKS])
        await session.commit()

    await engine.dispose()
    print(f"Imported {len(BOOKS)} real books (old catalogue removed).")
    print("Image filenames (place matching files in book_images/):")
    for b in BOOKS:
        print(f"  {_slug(b['title'])}.jpg  <-  {b['title']}")


if __name__ == "__main__":
    asyncio.run(main())
