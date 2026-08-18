from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot import ai
from bot import repository as repo
from bot.config import settings
from bot.keyboards import AI_ENTER_TEXT, AI_EXIT_TEXT, ai_chat_kb, request_location_kb
from bot.states import AiChat

router = Router()

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
