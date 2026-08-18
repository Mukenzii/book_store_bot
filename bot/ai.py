"""The AI book assistant: answers customer questions using the books table.

This is Retrieval-Augmented Generation (RAG), not fine-tuning — we pull the
books relevant to the question out of Postgres and hand them to Claude as
context on every call. New book? Just add a row; the assistant sees it
immediately, and it can never invent a title or price that isn't in the table.

One Claude API call per question (a single-turn Q&A — no tools, no agent loop).
"""

import logging

from bot.config import settings
from bot.models import Book

logger = logging.getLogger(__name__)

# Lazily-built async client (only if a key is configured).
_client = None

# Messages shown to the user when the model can't answer for operational reasons.
_DISABLED = (
    "🤖 AI yordamchi hozircha yoqilmagan. Iltimos, keyinroq urinib ko‘ring."
)
_BUSY = "🤖 Hozir yordamchiga murojaatlar ko‘p. Bir necha soniyadan so‘ng qayta urinib ko‘ring."
_ERROR = "🤖 Kechirasiz, javob berishda xatolik yuz berdi. Birozdan so‘ng qayta urinib ko‘ring."
_CANT = (
    "🤖 Kechirasiz, bu savolga javob bera olmayman. Kitoblarimiz haqida "
    "so‘rasangiz, yordam beraman."
)

# The publishing-house persona. Kept in one place so its "voice" is consistent.
_HOUSE = (
    "Sen — «Falaq Nashr» nashriyotining kitob bo‘yicha maslahatchisisan. "
    "Vazifang: mijozlarga faqat bizning katalogimizdagi kitoblar asosida "
    "yordam berish — kitob tavsiya qilish, mazmuni, narxi, muallifi va mavjudligi "
    "haqida ma’lumot berish."
)

_RULES = (
    "\n\nQOIDALAR:\n"
    "1. Faqat quyidagi KATALOG’dagi kitoblardan foydalanib javob ber. "
    "Katalogda yo‘q kitobni o‘ylab topma yoki taxmin qilma.\n"
    "2. Mijoz so‘ragan kitob katalogda bo‘lmasa, buni ochiq ayt va shu mavzuga "
    "yaqin bor kitoblarni taklif qil.\n"
    "3. Mijozning tilida javob ber (odatda o‘zbekcha). Iliq, samimiy va qisqa yoz.\n"
    "4. Mos kitoblarni tavsiya qilganda nomi, muallifi va (agar mavjud bo‘lsa) "
    "narxini ayt. Kerak bo‘lsa qisqa izoh ber.\n"
    "5. Narx yoki mavjudlikni faqat katalogdagi ma’lumotga qarab ayt.\n"
    "6. Javobingda ichki yoki tizim XML teglaridan foydalanma."
)


def _get_client():
    global _client
    if not settings.ai_enabled:
        return None
    if _client is None:
        from anthropic import AsyncAnthropic  # imported lazily so the bot runs without the SDK/key

        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def _format_book(b: Book) -> str:
    """One catalogue line per book — compact, but everything the model needs."""
    parts = [f"#{b.id} «{b.title}»"]
    if b.author:
        parts.append(f"muallif: {b.author}")
    if b.genre:
        parts.append(f"janr: {b.genre}")
    if b.language:
        parts.append(f"til: {b.language}")
    if b.age_group:
        parts.append(f"yosh: {b.age_group}")
    if b.year:
        parts.append(f"yil: {b.year}")
    if b.price:
        parts.append(f"narx: {b.price}")
    parts.append("mavjud" if b.in_stock else "hozircha yo‘q")
    if b.annotation:
        parts.append(f"tavsif: {b.annotation.strip()}")
    return " | ".join(parts)


def _system_prompt(books: list[Book]) -> str:
    catalog = "\n".join(_format_book(b) for b in books) if books else "(katalog bo‘sh)"
    return f"{_HOUSE}{_RULES}\n\nKATALOG:\n{catalog}"


async def answer_question(question: str, books: list[Book]) -> str:
    """Ask Claude the customer's question against the retrieved catalogue slice."""
    client = _get_client()
    if client is None:
        return _DISABLED

    # Imported here so a missing SDK never breaks import of this module.
    from anthropic import APIError, RateLimitError

    try:
        resp = await client.messages.create(
            model=settings.ai_model,
            max_tokens=settings.ai_max_tokens,
            system=_system_prompt(books),
            messages=[{"role": "user", "content": question}],
        )
    except RateLimitError:
        return _BUSY
    except APIError as exc:  # noqa: BLE001 — any API failure degrades gracefully
        logger.warning("AI request failed: %s", exc)
        return _ERROR

    # Safety classifiers can decline; content is empty/partial on a refusal.
    if resp.stop_reason == "refusal":
        return _CANT

    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return text or _ERROR
