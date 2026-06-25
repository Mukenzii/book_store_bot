from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.models import Store
from bot.repository import StoreWithDistance


class StoreCallback(CallbackData, prefix="store"):
    """Carries the chosen store id through an inline-button press."""

    store_id: int


# --- admin callback factories ------------------------------------------------

class AdminMenu(CallbackData, prefix="adm"):
    action: str  # add | list | close


class AdminPage(CallbackData, prefix="admpage"):
    offset: int


class AdminStore(CallbackData, prefix="admst"):
    action: str  # view | delete | confirmdel | edit
    store_id: int


class AdminField(CallbackData, prefix="admfld"):
    store_id: int
    field: str  # name | phone | hours | description | location


class BroadcastCB(CallbackData, prefix="bcast"):
    action: str  # send | cancel


PAGE_SIZE = 8


def request_location_kb() -> ReplyKeyboardMarkup:
    """Reply keyboard with a native 'share location' button."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Joylashuvni yuborish", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Joylashuvni ulashish uchun tugmani bosing",
    )


def send_location_kb() -> ReplyKeyboardMarkup:
    """Reply keyboard used inside the admin add/edit flow to capture a pin."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Joylashuvni yuborish", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Do‘kon joylashuvini yuboring",
    )


def stores_list_kb(stores: list[StoreWithDistance]) -> InlineKeyboardMarkup:
    """Inline list of nearby stores, one button per store."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{store.name} · {store.distance_km:.1f} km",
                callback_data=StoreCallback(store_id=store.id).pack(),
            )
        ]
        for store in stores
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- admin keyboards ---------------------------------------------------------

def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Do‘kon qo‘shish", callback_data=AdminMenu(action="add").pack())],
            [InlineKeyboardButton(text="📋 Do‘konlar ro‘yxati", callback_data=AdminMenu(action="list").pack())],
            [InlineKeyboardButton(text="📢 Hammaga xabar yuborish", callback_data=AdminMenu(action="broadcast").pack())],
            [InlineKeyboardButton(text="✖️ Yopish", callback_data=AdminMenu(action="close").pack())],
        ]
    )


def admin_list_kb(stores: list[Store], offset: int, total: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"#{store.id} · {store.name}"[:60],
                callback_data=AdminStore(action="view", store_id=store.id).pack(),
            )
        ]
        for store in stores
    ]

    nav: list[InlineKeyboardButton] = []
    if offset > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=AdminPage(offset=max(0, offset - PAGE_SIZE)).pack()))
    if offset + PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=AdminPage(offset=offset + PAGE_SIZE).pack()))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="🔙 Menyu", callback_data=AdminMenu(action="menu").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_store_kb(store_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Nomi", callback_data=AdminField(store_id=store_id, field="name").pack()),
             InlineKeyboardButton(text="✏️ Telefon", callback_data=AdminField(store_id=store_id, field="phone").pack())],
            [InlineKeyboardButton(text="✏️ Ish vaqti", callback_data=AdminField(store_id=store_id, field="hours").pack()),
             InlineKeyboardButton(text="✏️ Tavsif", callback_data=AdminField(store_id=store_id, field="description").pack())],
            [InlineKeyboardButton(text="📍 Joylashuv", callback_data=AdminField(store_id=store_id, field="location").pack())],
            [InlineKeyboardButton(text="🗑 O‘chirish", callback_data=AdminStore(action="delete", store_id=store_id).pack())],
            [InlineKeyboardButton(text="📋 Ro‘yxatga qaytish", callback_data=AdminPage(offset=0).pack())],
        ]
    )


def admin_confirm_delete_kb(store_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha, o‘chirilsin", callback_data=AdminStore(action="confirmdel", store_id=store_id).pack())],
            [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data=AdminStore(action="view", store_id=store_id).pack())],
        ]
    )


def broadcast_confirm_kb(audience: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ {audience} ta foydalanuvchiga yuborish", callback_data=BroadcastCB(action="send").pack())],
            [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data=BroadcastCB(action="cancel").pack())],
        ]
    )
