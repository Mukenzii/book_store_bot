import re
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, InputMediaPhoto, Message

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
# Telegram photo/album caption limit.
_CAPTION_LIMIT = 1024


def _norm(s: str) -> str:
    """Lowercase and strip punctuation, so title matching ignores «», !, ' etc."""
    return re.sub(r"[^a-z0-9Ѐ-ӿ]", "", (s or "").lower())


def _fmt(text: str) -> str:
    """Render the model's Markdown-ish **bold** as HTML (the bot uses HTML mode)."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(text))

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

    # The catalogue is small, so hand the model the WHOLE list every time and let
    # it pick the genre-appropriate books itself — keyword search returned the
    # wrong subset for vibe queries like "detective". (When the catalogue grows
    # past ai_max_books, switch this to semantic retrieval.)
    books = await repo.sample_books(settings.ai_max_books)

    reply = await ai.answer_question(question, books)
    body = _fmt(reply)

    # Collect the info images for the catalogue books the assistant actually named.
    answer_norm = _norm(reply)
    seen: set[int] = set()
    images: list[Path] = []
    for b in books:
        if len(images) >= _MAX_IMAGES:
            break
        if b.id in seen or not b.image or len(_norm(b.title)) < 5:
            continue
        if _norm(b.title) in answer_norm:
            path = BOOK_IMAGES_DIR / b.image
            if path.is_file():
                seen.add(b.id)
                images.append(path)

    # No image → just the text. The text stays in AI mode (Back button visible).
    if not images:
        await message.answer(body, reply_markup=ai_chat_kb())
        return

    # Image(s) + text in ONE message: photo/album with the answer as the caption.
    fits = len(reply) <= _CAPTION_LIMIT
    if len(images) == 1:
        await message.answer_photo(
            FSInputFile(images[0]),
            caption=body if fits else None,
            reply_markup=ai_chat_kb(),
        )
    else:
        media = [
            InputMediaPhoto(media=FSInputFile(p), caption=body if (i == 0 and fits) else None)
            for i, p in enumerate(images)
        ]
        await message.answer_media_group(media)
    # Rare fallback: answer too long for a caption — send it as its own message.
    if not fits:
        await message.answer(body, reply_markup=ai_chat_kb())
