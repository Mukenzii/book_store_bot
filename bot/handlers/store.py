from html import escape
from pathlib import Path

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile

from bot import features
from bot.formatting import format_store_details
from bot.keyboards import StoreBookView, StoreCallback, store_books_kb
from bot.repository import get_book_by_id, get_store, get_store_book, list_store_books

BOOK_IMAGES_DIR = Path(__file__).resolve().parents[2] / "book_images"
_CAPTION_LIMIT = 1024

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
    # The store's available books, as buttons — tapping one shows its details.
    books = (
        await list_store_books(store.id)
        if features.enabled("store_books", callback.from_user.id)
        else []
    )
    if books:
        details += "\n\n📚 <b>Mavjud kitoblar</b> — batafsil ko‘rish uchun tanlang:"
        await callback.message.answer(
            details, reply_markup=store_books_kb(books[:_MAX_CARD_BOOKS])
        )
    else:
        await callback.message.answer(details)
    # A venue gives the user a tappable map pin they can open / route to.
    await callback.message.answer_venue(
        latitude=store.latitude,
        longitude=store.longitude,
        title=store.name,
        address=store.address or store.name,
    )


@router.callback_query(StoreBookView.filter())
async def show_store_book(callback: CallbackQuery, callback_data: StoreBookView) -> None:
    """Customer tapped a book on a store card — show cover, author, description."""
    if not features.enabled("store_books", callback.from_user.id):
        await callback.answer()
        return
    sb = await get_store_book(callback_data.sb_id)
    if sb is None:
        await callback.answer("Bu kitob endi mavjud emas.", show_alert=True)
        return
    await callback.answer()

    # Catalogue books carry a cover and description; free-text ones don't.
    book = await get_book_by_id(sb.book_id) if sb.book_id else None
    title = book.title if book else sb.title
    author = book.author if book else sb.author

    head = [f"<b>{escape(title)}</b>"]
    if author:
        head.append(f"Muallif: {escape(author)}")
    if book and book.genre:
        head.append(f"Janr: {escape(book.genre)}")
    if book and book.publisher:
        head.append(f"Nashriyot: {escape(book.publisher)}")
    if book and book.pages:
        head.append(f"Sahifalar: {book.pages}")
    text = "\n".join(head)

    if book and book.annotation:
        room = _CAPTION_LIMIT - len(text) - 60  # margin for escaping + "…"
        ann = book.annotation.strip()
        if len(ann) > room:
            ann = ann[:room].rstrip() + "…"
        text += "\n\n" + escape(ann)
    elif not book:
        text += "\n\nBu kitob haqida qo‘shimcha ma’lumot yo‘q."

    image = BOOK_IMAGES_DIR / book.image if book and book.image else None
    if image and image.is_file():
        await callback.message.answer_photo(FSInputFile(image), caption=text)
    else:
        await callback.message.answer(text)
