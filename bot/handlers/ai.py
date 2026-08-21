import re
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message

from bot import ai
from bot import repository as repo
from bot.config import settings
from bot.keyboards import AI_ENTER_TEXT, AI_EXIT_TEXT, ai_chat_kb, request_location_kb
from bot.states import AiChat

router = Router()

# Book info images live here (shipped inside the image via `COPY . .`).
BOOK_IMAGES_DIR = Path(__file__).resolve().parents[2] / "book_images"
# How many book images to send per answer (avoid flooding the chat).
_MAX_IMAGES = 4


def _norm(s: str) -> str:
    """Lowercase and strip punctuation, so title matching ignores «», !, ' etc."""
    return re.sub(r"[^a-z0-9Ѐ-ӿ]", "", (s or "").lower())

_INTRO = (
    "🤖 <b>Falaq Nashr AI yordamchisi</b>\n\n"
    "Qanday kitob qidiryapsiz? Menga savol bering — masalan:\n"
    "• «Bolalar uchun qanday kitoblaringiz bor?»\n"
    "• «Detektiv janridagi kitob tavsiya qiling»\n"
    "• «Falonchi muallifning kitoblari bormi?»\n\n"
    "Asosiy menyuga qaytish uchun «⬅️ Orqaga» tugmasini bosing."
)

_BACK = "Asosiy menyu. Joylashuvingizni yuboring 📍 yoki yana AI yordamchini oching 🤖"

_DISABLED = (
    "🤖 AI yordamchi hozircha ulanmagan. Tez orada ishga tushadi — hozircha "
    "joylashuvingizni yuboring, eng yaqin do‘konni topaman."
)


@router.message(F.text == AI_ENTER_TEXT)
async def enter_ai(message: Message, state: FSMContext) -> None:
    if not settings.ai_enabled:
        await message.answer(_DISABLED, reply_markup=request_location_kb())
        return
    await state.set_state(AiChat.active)
    await message.answer(_INTRO, reply_markup=ai_chat_kb())


@router.message(AiChat.active, F.text == AI_EXIT_TEXT)
async def back_to_menu(message: Message, state: FSMContext) -> None:
    # User pressed "Back" — stop the agent and restore the main menu buttons.
    await state.clear()
    await message.answer(_BACK, reply_markup=request_location_kb())


@router.message(AiChat.active, F.text & ~F.text.startswith("/"))
async def ask_ai(message: Message, state: FSMContext) -> None:
    question = message.text.strip()
    if not question:
        return
    await message.bot.send_chat_action(message.chat.id, "typing")

    books = await repo.search_books(question, settings.ai_max_books)
    if not books:
        # No keyword match — hand the model a slice of the catalogue so it can
        # still recommend something rather than drawing a blank.
        books = await repo.sample_books(settings.ai_max_books)

    reply = await ai.answer_question(question, books)
    # Stay in AI mode — the user keeps asking until they press "⬅️ Orqaga".
    await message.answer(reply, reply_markup=ai_chat_kb())

    # Send the info image for each catalogue book the assistant actually named,
    # so the book details reach the user inside the image.
    answer_norm = _norm(reply)
    seen: set[int] = set()
    sent = 0
    for b in books:
        if sent >= _MAX_IMAGES:
            break
        if b.id in seen or not b.image or len(_norm(b.title)) < 5:
            continue
        if _norm(b.title) in answer_norm:
            path = BOOK_IMAGES_DIR / b.image
            if path.is_file():
                seen.add(b.id)
                sent += 1
                await message.answer_photo(
                    FSInputFile(path), caption=f"📖 <b>{b.title}</b>"
                )
