"""Customer: which stores have a book.

📚 Kitoblar → books that at least one store listed (owners add them via
/dokonim) → tap one → its card + the nearest stores that have it. If the bot
doesn't know the user's location yet, it asks for it and the location handler
finishes the search (the chosen book waits in FSM data as `book_id`).
"""

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import features
from bot import repository as repo
from bot.config import settings
from bot.handlers.store import send_book_card
from bot.keyboards import (
    BOOKS_TEXT,
    AvailBook,
    AvailBookPage,
    available_books_kb,
    request_location_kb,
    stores_list_kb,
)
from bot.states import StoreSearch

router = Router()

_EMPTY = "Hozircha do‘konlar o‘z kitoblarini kiritmagan. Keyinroq qayta urinib ko‘ring."
_LIST = "📚 Do‘konlarda mavjud kitoblar. Kitobni tanlang — u bor eng yaqin do‘konlarni ko‘rsataman 👇"


def _on(user_id: int) -> bool:
    return features.enabled("book_stores", user_id)


async def _books(user_id: int):
    # Testers also see the private Test do‘kon's books, so they can try the flow.
    return await repo.books_in_stores(include_test=features.in_test_env(user_id))


async def nearest_with_book(user_id: int, lat: float, lon: float, book_id: int):
    stores = await repo.find_nearest_stores_with_book(
        lat, lon, settings.nearest_limit, book_id, include_test=features.in_test_env(user_id)
    )
    book = await repo.get_book_by_id(book_id)
    return book, stores


def stores_text(book, stores) -> str:
    title = escape(book.title) if book else "Bu kitob"
    if not stores:
        return f"😕 «{title}» hozircha hech bir do‘konda kiritilmagan."
    return f"«{title}» bor eng yaqin {len(stores)} ta do‘kon. Tafsilotlar uchun birini tanlang 👇"


@router.message(F.text == BOOKS_TEXT, F.from_user.func(lambda u: _on(u.id)))
async def list_books(message: Message, state: FSMContext) -> None:
    items = await _books(message.from_user.id)
    if not items:
        await message.answer(_EMPTY, reply_markup=request_location_kb(message.from_user.id))
        return
    await message.answer(_LIST, reply_markup=available_books_kb(items, 0))


@router.callback_query(AvailBookPage.filter())
async def page_books(callback: CallbackQuery, callback_data: AvailBookPage) -> None:
    await callback.answer()
    if not _on(callback.from_user.id):
        return
    items = await _books(callback.from_user.id)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=available_books_kb(items, callback_data.offset)
        )
    except Exception:  # noqa: BLE001 — unchanged/expired message
        pass


@router.callback_query(AvailBook.filter())
async def show_book(callback: CallbackQuery, callback_data: AvailBook, state: FSMContext) -> None:
    uid = callback.from_user.id
    if not _on(uid):
        await callback.answer()
        return
    book = await repo.get_book_by_id(callback_data.book_id)
    if book is None:
        await callback.answer("Bu kitob endi mavjud emas.", show_alert=True)
        return
    await callback.answer()
    await send_book_card(callback.message, book)

    data = await state.get_data()
    lat, lon = data.get("lat"), data.get("lon")
    if lat is None or lon is None:
        # Ask for the location; handle_location finishes with this book.
        await state.update_data(book_id=book.id)
        await callback.message.answer(
            "Bu kitob bor eng yaqin do‘konlarni topishim uchun joylashuvingizni yuboring 📍",
            reply_markup=request_location_kb(uid),
        )
        return

    book, stores = await nearest_with_book(uid, lat, lon, book.id)
    await state.set_state(StoreSearch.choosing_store)
    if stores:
        await callback.message.answer(stores_text(book, stores), reply_markup=stores_list_kb(stores))
    else:
        await callback.message.answer(stores_text(book, stores))
