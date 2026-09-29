from html import escape

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.formatting import format_store_details
from bot.keyboards import StoreCallback
from bot.repository import get_store, list_store_books

# Cap the number of books listed on a store card so the message stays readable.
_MAX_CARD_BOOKS = 30

router = Router()


@router.callback_query(StoreCallback.filter())
async def show_store(
    callback: CallbackQuery,
    callback_data: StoreCallback,
    state: FSMContext,
) -> None:
    """User tapped a store from the list — send its full details + map pin."""
    data = await state.get_data()
    lat = data.get("lat")
    lon = data.get("lon")

    if lat is None or lon is None:
        await callback.answer()
        await callback.message.answer(
            "Joylashuvingiz eskirdi. Iltimos, /start orqali qaytadan yuboring."
        )
        return

    store = await get_store(callback_data.store_id, lat, lon)
    if store is None:
        await callback.answer("Bu do‘kon endi mavjud emas.", show_alert=True)
        return

    await callback.answer()

    details = format_store_details(store)
    # Append the store's approved available books, if any.
    books = await list_store_books(store.id, approved_only=True)
    if books:
        lines = ["", "📚 <b>Mavjud kitoblar:</b>"]
        for b in books[:_MAX_CARD_BOOKS]:
            line = f"• {escape(b.title)}"
            if b.author:
                line += f" — {escape(b.author)}"
            lines.append(line)
        if len(books) > _MAX_CARD_BOOKS:
            lines.append(f"… va yana {len(books) - _MAX_CARD_BOOKS} ta")
        details += "\n" + "\n".join(lines)
    await callback.message.answer(details)
    # A venue gives the user a tappable map pin they can open / route to.
    await callback.message.answer_venue(
        latitude=store.latitude,
        longitude=store.longitude,
        title=store.name,
        address=store.address or store.name,
    )
