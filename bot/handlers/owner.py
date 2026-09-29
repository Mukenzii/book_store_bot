"""Store-owner flow: manage the books available at your store.

Ownership is by phone (the owner's idea): a store's admin-entered `phone` is the
owner's key. A Telegram user opens /dokonim; if their shared phone matches one
or more stores, they can add books (from the catalogue or free-text) to those
stores. Added books show to customers on the store's card immediately.
"""

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import features
from bot import repository as repo
from bot.keyboards import (
    PAGE_SIZE,
    OwnerAdd,
    OwnerCat,
    OwnerDel,
    OwnerMenu,
    owner_books_kb,
    owner_catalog_kb,
    owner_panel_kb,
    owner_stores_kb,
)
from bot.states import OwnerAddBook

router = Router()

_NOT_OWNER = (
    "🏪 Sizning telefon raqamingizga biriktirilgan do‘kon topilmadi.\n\n"
    "Do‘kon egasi bo‘lsangiz — administrator sizning raqamingizni do‘kon "
    "ma’lumotlariga qo‘shishi kerak. So‘ng bu yerdan kitoblaringizni qo‘shasiz."
)
_NO_PHONE = (
    "Avval telefon raqamingizni ulashing: /start bosing va «📱 Telefon "
    "raqamni yuborish» tugmasini bosing. So‘ng /dokonim orqali qayting."
)


async def _panel_text(store) -> str:
    books = await repo.list_store_books(store.id)
    return (
        f"🏪 <b>{escape(store.name)}</b>\n"
        f"Mavjud kitoblar: <b>{len(books)}</b>\n\n"
        "Quyidagidan birini tanlang:"
    )


async def _show_panel(message: Message, store) -> None:
    await message.answer(await _panel_text(store), reply_markup=owner_panel_kb(store.id))


async def _my_stores(user_id: int) -> list | None:
    """Stores this user owns. In test mode you are automatically the owner of
    the private test store (or of a store you picked via «Egasi sifatida
    sinash»); everyone else is matched by phone. None = no phone yet."""
    sid = features.acting_owner_store(user_id)
    if sid is not None:
        store = await repo.get_store_by_id(sid)
        return [store] if store else []
    if features.is_tester(user_id):
        return [await repo.get_or_create_test_store()]
    user = await repo.get_user(user_id)
    if not (user and user.phone):
        return None
    return await repo.stores_owned_by_phone(user.phone)


async def _owned_store(user_id: int, store_id: int):
    """Re-check ownership on every action so a callback can't touch a store the
    user doesn't own (or a feature still in testing)."""
    if not features.enabled("store_books", user_id):
        return None
    for s in await _my_stores(user_id) or []:
        if s.id == store_id:
            return s
    return None


@router.message(Command("dokonim"))
async def cmd_my_store(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not features.enabled("store_books", message.from_user.id):
        await message.answer("Bu funksiya tez orada ishga tushadi.")
        return
    stores = await _my_stores(message.from_user.id)
    if stores is None:
        await message.answer(_NO_PHONE)
        return
    if not stores:
        await message.answer(_NOT_OWNER)
        return
    if len(stores) == 1:
        await _show_panel(message, stores[0])
        return
    await message.answer(
        "Sizda bir nechta do‘kon bor. Qaysi birini boshqaramiz?",
        reply_markup=owner_stores_kb(stores),
    )


@router.callback_query(OwnerMenu.filter(F.action == "panel"))
async def on_panel(callback: CallbackQuery, callback_data: OwnerMenu, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    store = await _owned_store(callback.from_user.id, callback_data.store_id)
    if store is None:
        await callback.message.answer(_NOT_OWNER)
        return
    await _show_panel(callback.message, store)


@router.callback_query(OwnerMenu.filter(F.action == "mybooks"))
async def on_my_books(callback: CallbackQuery, callback_data: OwnerMenu) -> None:
    await callback.answer()
    store = await _owned_store(callback.from_user.id, callback_data.store_id)
    if store is None:
        await callback.message.answer(_NOT_OWNER)
        return
    books = await repo.list_store_books(store.id)
    if not books:
        await callback.message.answer(
            "Hozircha kitob qo‘shmagansiz. «➕ Katalogdan» yoki «✍️ Boshqa kitob» orqali qo‘shing.",
            reply_markup=owner_panel_kb(store.id),
        )
        return
    await callback.message.answer(
        "📚 <b>Kitoblaringiz</b>. O‘chirish uchun bosing:",
        reply_markup=owner_books_kb(store.id, books),
    )


@router.callback_query(OwnerDel.filter())
async def on_delete(callback: CallbackQuery, callback_data: OwnerDel) -> None:
    store = await _owned_store(callback.from_user.id, callback_data.store_id)
    if store is None:
        await callback.answer("Ruxsat yo‘q.", show_alert=True)
        return
    await repo.delete_store_book(callback_data.sb_id, store.id)
    await callback.answer("O‘chirildi")
    books = await repo.list_store_books(store.id)
    if books:
        await callback.message.edit_reply_markup(reply_markup=owner_books_kb(store.id, books))
    else:
        await callback.message.answer(await _panel_text(store), reply_markup=owner_panel_kb(store.id))


async def _show_catalog(message: Message, store_id: int, offset: int) -> None:
    total = await repo.count_books()
    books = await repo.list_books(PAGE_SIZE, offset)
    if not books:
        await message.answer("Katalog bo‘sh.", reply_markup=owner_panel_kb(store_id))
        return
    page = offset // PAGE_SIZE + 1
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    await message.answer(
        f"➕ <b>Katalogdan tanlang</b> ({page}/{pages}) — qo‘shish uchun bosing:",
        reply_markup=owner_catalog_kb(store_id, books, offset, total),
    )


@router.callback_query(OwnerMenu.filter(F.action == "addcat"))
async def on_add_catalog(callback: CallbackQuery, callback_data: OwnerMenu) -> None:
    await callback.answer()
    store = await _owned_store(callback.from_user.id, callback_data.store_id)
    if store is None:
        await callback.message.answer(_NOT_OWNER)
        return
    await _show_catalog(callback.message, store.id, 0)


@router.callback_query(OwnerCat.filter())
async def on_catalog_page(callback: CallbackQuery, callback_data: OwnerCat) -> None:
    await callback.answer()
    store = await _owned_store(callback.from_user.id, callback_data.store_id)
    if store is None:
        await callback.message.answer(_NOT_OWNER)
        return
    await _show_catalog(callback.message, store.id, callback_data.offset)


@router.callback_query(OwnerAdd.filter())
async def on_add_book(callback: CallbackQuery, callback_data: OwnerAdd) -> None:
    store = await _owned_store(callback.from_user.id, callback_data.store_id)
    if store is None:
        await callback.answer("Ruxsat yo‘q.", show_alert=True)
        return
    book = await repo.get_book_by_id(callback_data.book_id)
    if book is None:
        await callback.answer("Kitob topilmadi.", show_alert=True)
        return
    sb = await repo.add_store_book(
        store.id, book_id=book.id, title=book.title, author=book.author,
        added_by=callback.from_user.id,
    )
    await callback.answer("Qo‘shildi" if sb else "Bu kitob allaqachon qo‘shilgan")


@router.callback_query(OwnerMenu.filter(F.action == "addcustom"))
async def on_add_custom(callback: CallbackQuery, callback_data: OwnerMenu, state: FSMContext) -> None:
    await callback.answer()
    store = await _owned_store(callback.from_user.id, callback_data.store_id)
    if store is None:
        await callback.message.answer(_NOT_OWNER)
        return
    await state.set_state(OwnerAddBook.title)
    await state.update_data(store_id=store.id)
    await callback.message.answer("✍️ Kitob <b>nomini</b> kiriting (bekor qilish: /cancel):")


@router.message(OwnerAddBook.title, F.text)
async def custom_title(message: Message, state: FSMContext) -> None:
    if message.text.startswith("/"):
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(OwnerAddBook.author)
    await message.answer("✍️ Muallifini kiriting («-» — noma’lum):")


@router.message(OwnerAddBook.author, F.text)
async def custom_author(message: Message, state: FSMContext) -> None:
    if message.text.startswith("/"):
        return
    data = await state.get_data()
    await state.clear()
    store = await _owned_store(message.from_user.id, data.get("store_id", 0))
    if store is None:
        await message.answer(_NOT_OWNER)
        return
    author = message.text.strip()
    author = None if author in {"-", "—", "."} else author
    sb = await repo.add_store_book(
        store.id, book_id=None, title=data.get("title", ""), author=author,
        added_by=message.from_user.id,
    )
    if sb:
        await message.answer("Qo‘shildi — mijozlar uni do‘kon kartasida ko‘radi.")
    else:
        await message.answer("Bu kitob allaqachon ro‘yxatda bor.")
    await _show_panel(message, store)
