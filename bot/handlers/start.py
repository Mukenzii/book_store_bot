from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import request_location_kb

router = Router()

WELCOME = (
    "👋 <b>Kitob do‘konlari qidiruvchisiga xush kelibsiz!</b>\n\n"
    "Men sizga kitoblarimiz sotiladigan eng yaqin do‘konni topishda yordam beraman.\n\n"
    "Joylashuvingizni yuboring va men eng yaqin do‘konlar ro‘yxatini ko‘rsataman. "
    "So‘ng do‘konni tanlang — uning manzili, ish vaqti va telefon raqamini ko‘rasiz."
)

HELP = (
    "Menga joylashuvingizni yuboring (pastdagi 📍 tugmani bosing) va men eng yaqin "
    "kitob do‘konlarini topaman.\n\n"
    "Buyruqlar:\n"
    "/start — qaytadan boshlash va joylashuvni yuborish\n"
    "/help — ushbu xabarni ko‘rsatish"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME, reply_markup=request_location_kb())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=request_location_kb())
