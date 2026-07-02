from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot import repository as repo
from bot.keyboards import request_location_kb, request_phone_kb

router = Router()

WELCOME = (
    "👋 <b>Kitob do‘konlari qidiruvchisiga xush kelibsiz!</b>\n\n"
    "Men sizga kitoblarimiz sotiladigan eng yaqin do‘konni topishda yordam beraman.\n\n"
    "Joylashuvingizni yuboring va men eng yaqin do‘konlar ro‘yxatini ko‘rsataman. "
    "So‘ng do‘konni tanlang — uning manzili, ish vaqti va telefon raqamini ko‘rasiz."
)

ASK_PHONE = (
    "👋 <b>Assalomu alaykum!</b>\n\n"
    "Botdan foydalanish uchun, iltimos, telefon raqamingizni ulashing. "
    "Pastdagi <b>«📱 Telefon raqamni yuborish»</b> tugmasini bosing 👇"
)

HELP = (
    "Menga joylashuvingizni yuboring (pastdagi 📍 tugmani bosing) va men eng yaqin "
    "kitob do‘konlarini topaman.\n\n"
    "Buyruqlar:\n"
    "/start — qaytadan boshlash\n"
    "/help — ushbu xabarni ko‘rsatish"
)


async def _has_phone(user_id: int) -> bool:
    user = await repo.get_user(user_id)
    return bool(user and user.phone)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    # First visit (no phone on file) → ask for it. Returning user → recognised.
    if await _has_phone(message.from_user.id):
        await message.answer(
            f"Xush kelibsiz, {message.from_user.first_name}! 👋",
        )
        await message.answer(WELCOME, reply_markup=request_location_kb())
    else:
        await message.answer(ASK_PHONE, reply_markup=request_phone_kb())


@router.message(F.contact)
async def on_contact(message: Message, state: FSMContext) -> None:
    contact = message.contact
    # Only accept the user's OWN number, not a forwarded/other contact.
    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer(
            "Iltimos, o‘zingizning raqamingizni ulashing.",
            reply_markup=request_phone_kb(),
        )
        return

    await repo.set_user_phone(message.from_user.id, contact.phone_number)
    await state.clear()
    await message.answer("✅ Rahmat! Ro‘yxatdan o‘tdingiz.")
    await message.answer(WELCOME, reply_markup=request_location_kb())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=request_location_kb())
