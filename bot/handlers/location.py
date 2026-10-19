from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot import features
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

    # The user picked a book in 📚 Kitoblar and was asked for their location:
    # show the nearest stores that have THAT book, then forget the choice.
    book_id = (await state.get_data()).get("book_id")
    if book_id and features.enabled("book_stores", message.from_user.id):
        from bot.handlers.books import nearest_with_book, stores_text

        book, stores = await nearest_with_book(message.from_user.id, lat, lon, book_id)
        await state.set_state(StoreSearch.choosing_store)
        await state.update_data(lat=lat, lon=lon, book_id=None)
        await message.answer(
            stores_text(book, stores), reply_markup=stores_list_kb(stores) if stores else None
        )
        return

    stores = await find_nearest_stores(lat, lon, settings.nearest_limit)
    # Test mode: put the private test store first so the tester can check what
    # customers will see. Real customers never get it (it's excluded above).
    if features.in_test_env(message.from_user.id):
        test = await repo.get_or_create_test_store()
        test_row = await repo.get_store(test.id, lat, lon)
        if test_row:
            stores = [test_row] + stores

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

    # One message (not two): the store list rides on an inline keyboard, and the
    # 📍 location button is already persistent (is_persistent=True), so it stays
    # visible on its own. Fewer Telegram round-trips = a snappier reply on a slow
    # link.
    await message.answer(
        f"Sizga eng yaqin {len(stores)} ta do‘kon. "
        "Tafsilotlarini ko‘rish uchun birini tanlang 👇",
        reply_markup=stores_list_kb(stores),
    )


@router.message(F.text & ~F.text.startswith("/"))
async def handle_unexpected_text(message: Message) -> None:
    """Any plain text that isn't a command — nudge the user to share location."""
    await message.answer(
        "Eng yaqin do‘konlarni topishim uchun joylashuvingizni yuboring 📍",
        reply_markup=request_location_kb(message.from_user.id),
    )
