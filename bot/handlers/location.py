from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot import repository as repo
from bot.config import settings
from bot.keyboards import request_location_kb, request_phone_kb, stores_list_kb
from bot.repository import find_nearest_stores
from bot.states import StoreSearch

router = Router()

ASK_PHONE = (
    "Botdan foydalanish uchun avval telefon raqamingizni ulashing 👇"
)


@router.message(F.location)
async def handle_location(message: Message, state: FSMContext) -> None:
    """User shared a location — find and offer the nearest stores."""
    # Require a phone number on file before serving results.
    user = await repo.get_user(message.from_user.id)
    if not (user and user.phone):
        await message.answer(ASK_PHONE, reply_markup=request_phone_kb())
        return

    lat = message.location.latitude
    lon = message.location.longitude

    stores = await find_nearest_stores(lat, lon, settings.nearest_limit)

    if not stores:
        await message.answer(
            "😕 Kechirasiz, hozircha bazada hech qanday do‘kon topilmadi. "
            "Iltimos, keyinroq urinib ko‘ring."
        )
        return

    # Remember the user's coordinates so the next step can compute distance
    # to whichever store they tap.
    await state.set_state(StoreSearch.choosing_store)
    await state.update_data(lat=lat, lon=lon)

    # Keep the location button visible (don't remove the reply keyboard) so the
    # user can search again anytime.
    await message.answer(
        f"Sizga eng yaqin {len(stores)} ta do‘kon. "
        "Tafsilotlarini ko‘rish uchun birini tanlang 👇",
        reply_markup=request_location_kb(),
    )
    await message.answer(
        "Eng yaqin kitob do‘konlari:",
        reply_markup=stores_list_kb(stores),
    )


@router.message(F.text & ~F.text.startswith("/"))
async def handle_unexpected_text(message: Message) -> None:
    """Any plain text that isn't a command — nudge the user to share location."""
    await message.answer(
        "Eng yaqin do‘konlarni topishim uchun joylashuvingizni yuboring 📍",
        reply_markup=request_location_kb(),
    )
