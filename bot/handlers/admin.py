from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from bot.broadcast import broadcast_copy
from bot.filters import IsAdmin
from bot.formatting import format_store_admin
from bot.keyboards import (
    PAGE_SIZE,
    AdminField,
    AdminMenu,
    AdminPage,
    AdminStore,
    BroadcastCB,
    admin_confirm_delete_kb,
    admin_list_kb,
    admin_menu_kb,
    admin_store_kb,
    broadcast_confirm_kb,
    send_location_kb,
)
from bot import repository as repo
from bot.states import AddStore, Broadcast, EditStore

# Every handler here is gated to admins for both messages and callbacks.
router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

# Words an admin can type to leave an optional field empty.
_SKIP = {"-", "—", "skip", "yoq", "yo'q", "yo‘q", "."}

FIELD_LABELS = {
    "name": "nom",
    "phone": "telefon",
    "hours": "ish vaqti",
    "description": "tavsif",
    "location": "joylashuv",
}
# Maps the short field key to the actual Store column name.
FIELD_COLUMN = {"hours": "working_hours"}


def _col(field: str) -> str:
    return FIELD_COLUMN.get(field, field)


def _clean(text: str) -> str | None:
    text = (text or "").strip()
    return None if text.lower() in _SKIP else text


# --- entry point -------------------------------------------------------------

async def _menu_text() -> str:
    stores = await repo.count_stores()
    total_users, active_users = await repo.count_users()
    return (
        "🛠 <b>Admin panel</b>\n"
        f"📚 Do‘konlar: <b>{stores}</b>\n"
        f"👥 Foydalanuvchilar: <b>{total_users}</b> (faol: {active_users})"
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(await _menu_text(), reply_markup=admin_menu_kb())


@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    await cmd_admin(message, state)


# --- menu navigation ---------------------------------------------------------

async def _show_list(target: Message, offset: int) -> None:
    total = await repo.count_stores()
    stores = await repo.list_stores(PAGE_SIZE, offset)
    if not stores:
        await target.answer("Hozircha do‘konlar yo‘q. ➕ orqali qo‘shing.", reply_markup=admin_menu_kb())
        return
    page = offset // PAGE_SIZE + 1
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    await target.answer(
        f"📋 Do‘konlar ({offset + 1}–{offset + len(stores)} / {total}) · {page}/{pages}",
        reply_markup=admin_list_kb(stores, offset, total),
    )


@router.callback_query(AdminMenu.filter())
async def on_menu(callback: CallbackQuery, callback_data: AdminMenu, state: FSMContext) -> None:
    await callback.answer()
    if callback_data.action == "close":
        await callback.message.delete()
        return
    if callback_data.action == "list":
        await _show_list(callback.message, 0)
        return
    if callback_data.action == "menu":
        await state.clear()
        await callback.message.answer(await _menu_text(), reply_markup=admin_menu_kb())
        return
    if callback_data.action == "add":
        await state.set_state(AddStore.name)
        await callback.message.answer(
            "➕ <b>Yangi do‘kon</b>\n\nDo‘kon <b>nomini</b> kiriting:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if callback_data.action == "broadcast":
        await state.set_state(Broadcast.message)
        await callback.message.answer(
            "📢 <b>Hammaga xabar</b>\n\n"
            "Yubormoqchi bo‘lgan xabaringizni shu yerga yuboring "
            "(matn, rasm, rasm + izoh — istalgan ko‘rinishda).\n\n"
            "Bekor qilish uchun /cancel.",
            reply_markup=ReplyKeyboardRemove(),
        )


@router.callback_query(AdminPage.filter())
async def on_page(callback: CallbackQuery, callback_data: AdminPage) -> None:
    await callback.answer()
    await _show_list(callback.message, callback_data.offset)


@router.callback_query(AdminStore.filter(F.action == "view"))
async def on_view(callback: CallbackQuery, callback_data: AdminStore) -> None:
    await callback.answer()
    store = await repo.get_store_by_id(callback_data.store_id)
    if store is None:
        await callback.message.answer("Do‘kon topilmadi.")
        return
    await callback.message.answer(format_store_admin(store), reply_markup=admin_store_kb(store.id))


# --- delete ------------------------------------------------------------------

@router.callback_query(AdminStore.filter(F.action == "delete"))
async def on_delete_prompt(callback: CallbackQuery, callback_data: AdminStore) -> None:
    await callback.answer()
    await callback.message.answer(
        "⚠️ Ushbu do‘kon o‘chirilsinmi?",
        reply_markup=admin_confirm_delete_kb(callback_data.store_id),
    )


@router.callback_query(AdminStore.filter(F.action == "confirmdel"))
async def on_delete_confirm(callback: CallbackQuery, callback_data: AdminStore) -> None:
    ok = await repo.delete_store(callback_data.store_id)
    await callback.answer("O‘chirildi" if ok else "Topilmadi", show_alert=True)
    await _show_list(callback.message, 0)


# --- edit a single field -----------------------------------------------------

@router.callback_query(AdminField.filter())
async def on_edit_field(callback: CallbackQuery, callback_data: AdminField, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(EditStore.value)
    await state.update_data(store_id=callback_data.store_id, field=callback_data.field)

    if callback_data.field == "location":
        await callback.message.answer(
            "Yangi <b>joylashuvni</b> yuboring:", reply_markup=send_location_kb()
        )
    else:
        label = FIELD_LABELS[callback_data.field]
        await callback.message.answer(
            f"Yangi <b>{label}</b>ni kiriting (bo‘sh qoldirish uchun «-»):",
            reply_markup=ReplyKeyboardRemove(),
        )


@router.message(EditStore.value, F.location)
async def on_edit_location(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await repo.update_store(
        data["store_id"],
        latitude=message.location.latitude,
        longitude=message.location.longitude,
    )
    await state.clear()
    store = await repo.get_store_by_id(data["store_id"])
    await message.answer("✅ Joylashuv yangilandi.", reply_markup=ReplyKeyboardRemove())
    await message.answer(format_store_admin(store), reply_markup=admin_store_kb(store.id))


@router.message(EditStore.value, F.text)
async def on_edit_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data["field"]
    if field == "location":
        await message.answer("Iltimos, 📍 tugma orqali joylashuv yuboring.")
        return

    value = _clean(message.text)
    if field == "name" and not value:
        await message.answer("Nom bo‘sh bo‘lishi mumkin emas. Qaytadan kiriting:")
        return

    await repo.update_store(data["store_id"], **{_col(field): value})
    await state.clear()
    store = await repo.get_store_by_id(data["store_id"])
    await message.answer("✅ Yangilandi.")
    await message.answer(format_store_admin(store), reply_markup=admin_store_kb(store.id))


# --- add a new store (multi-step) -------------------------------------------

@router.message(AddStore.name, F.text)
async def add_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("Nom bo‘sh bo‘lishi mumkin emas. Qaytadan kiriting:")
        return
    await state.update_data(name=name)
    await state.set_state(AddStore.location)
    await message.answer("📍 Do‘kon <b>joylashuvini</b> yuboring:", reply_markup=send_location_kb())


@router.message(AddStore.location, F.location)
async def add_location(message: Message, state: FSMContext) -> None:
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await state.set_state(AddStore.phone)
    await message.answer(
        "☎️ <b>Telefon</b> raqamini kiriting (bo‘sh qoldirish uchun «-»):",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(AddStore.location)
async def add_location_invalid(message: Message) -> None:
    await message.answer("Iltimos, 📍 tugma orqali joylashuv yuboring.", reply_markup=send_location_kb())


@router.message(AddStore.phone, F.text)
async def add_phone(message: Message, state: FSMContext) -> None:
    await state.update_data(phone=_clean(message.text))
    await state.set_state(AddStore.hours)
    await message.answer("🕒 <b>Ish vaqtini</b> kiriting (masalan: 09:00–21:00, «-» bo‘sh):")


@router.message(AddStore.hours, F.text)
async def add_hours(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    store = await repo.create_store(
        name=data["name"],
        latitude=data["lat"],
        longitude=data["lon"],
        phone=data.get("phone"),
        working_hours=_clean(message.text),
        address=None,
        description=None,
    )
    await state.clear()
    await message.answer("✅ Do‘kon qo‘shildi!")
    await message.answer(format_store_admin(store), reply_markup=admin_store_kb(store.id))


# --- broadcast to all users --------------------------------------------------

@router.message(Broadcast.message)
async def broadcast_preview(message: Message, state: FSMContext) -> None:
    # Remember which message to copy, then show a preview + confirm button.
    await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(Broadcast.confirm)

    _total, active = await repo.count_users()
    await message.answer("👆 Mana shu xabar yuboriladi. Tasdiqlaysizmi?")
    await message.answer(
        f"Qabul qiluvchilar: <b>{active}</b> ta faol foydalanuvchi.",
        reply_markup=broadcast_confirm_kb(active),
    )


@router.callback_query(BroadcastCB.filter(F.action == "cancel"), Broadcast.confirm)
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Bekor qilindi")
    await callback.message.answer(await _menu_text(), reply_markup=admin_menu_kb())


@router.callback_query(BroadcastCB.filter(F.action == "send"), Broadcast.confirm)
async def broadcast_send(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    status = await callback.message.answer("📤 Yuborilmoqda… (bu biroz vaqt olishi mumkin)")

    result = await broadcast_copy(
        callback.bot,
        from_chat_id=data["from_chat_id"],
        message_id=data["message_id"],
    )

    await status.edit_text(
        "✅ <b>Yuborildi!</b>\n"
        f"📨 Yetkazildi: <b>{result.sent}</b>\n"
        f"🚫 Bloklagan: <b>{result.blocked}</b>\n"
        f"⚠️ Xatolik: <b>{result.failed}</b>\n"
        f"👥 Jami: <b>{result.total}</b>"
    )
    await callback.message.answer(await _menu_text(), reply_markup=admin_menu_kb())
