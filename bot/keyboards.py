from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.models import ScheduledPost, Store
from bot.repository import StoreWithDistance

# Uzbek weekday names, indexed by datetime.weekday() (0=Mon … 6=Sun).
WEEKDAY_NAMES = [
    "Dushanba",
    "Seshanba",
    "Chorshanba",
    "Payshanba",
    "Juma",
    "Shanba",
    "Yakshanba",
]


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


class SchedMenu(CallbackData, prefix="sch"):
    action: str  # days | list | add | menu


class SchedDay(CallbackData, prefix="schday"):
    weekday: int  # toggle this weekday on/off in the days view


class SchedPick(CallbackData, prefix="schpick"):
    weekday: int  # pick this weekday for a new scheduled post


class SchedPost(CallbackData, prefix="schpost"):
    action: str  # view | delete | confirmdel
    post_id: int


class AdminMgmt(CallbackData, prefix="admgmt"):
    action: str  # add | remove | confirmrm | back
    user_id: int = 0


PAGE_SIZE = 8


def request_location_kb() -> ReplyKeyboardMarkup:
    """Reply keyboard with a native 'share location' button.

    one_time_keyboard=False so the button stays visible — the user can keep
    sending new locations without it ever disappearing.
    """
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Joylashuvni yuborish", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
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


def request_phone_kb() -> ReplyKeyboardMarkup:
    """Reply keyboard with a native 'share phone number' button (first visit)."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Telefon raqamingizni ulashing",
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
            [InlineKeyboardButton(text="📅 Rejalashtirilgan postlar", callback_data=AdminMenu(action="schedule").pack())],
            [InlineKeyboardButton(text="👑 Adminlar", callback_data=AdminMenu(action="admins").pack())],
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


# --- scheduled-posts keyboards -----------------------------------------------

def schedule_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗓 Kunlarni tanlash", callback_data=SchedMenu(action="days").pack())],
            [InlineKeyboardButton(text="➕ Post rejalashtirish", callback_data=SchedMenu(action="add").pack())],
            [InlineKeyboardButton(text="📋 Rejalashtirilgan postlar", callback_data=SchedMenu(action="list").pack())],
            [InlineKeyboardButton(text="🔙 Menyu", callback_data=AdminMenu(action="menu").pack())],
        ]
    )


def schedule_days_kb(enabled: set[int]) -> InlineKeyboardMarkup:
    """Toggle buttons for each weekday (✅ enabled / ⬜ disabled)."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅' if i in enabled else '⬜'} {name}",
                callback_data=SchedDay(weekday=i).pack(),
            )
        ]
        for i, name in enumerate(WEEKDAY_NAMES)
    ]
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data=SchedMenu(action="menu").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_pick_day_kb(enabled: set[int]) -> InlineKeyboardMarkup:
    """Buttons for the enabled weekdays, to pick a day for a new post."""
    rows = [
        [InlineKeyboardButton(text=WEEKDAY_NAMES[i], callback_data=SchedPick(weekday=i).pack())]
        for i in sorted(enabled)
    ]
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data=SchedMenu(action="menu").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def scheduled_list_kb(posts: list[ScheduledPost]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{WEEKDAY_NAMES[p.weekday]} {p.send_time} · {p.preview or 'post'}"[:60],
                callback_data=SchedPost(action="view", post_id=p.id).pack(),
            )
        ]
        for p in posts
    ]
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data=SchedMenu(action="menu").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def scheduled_post_kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 O‘chirish", callback_data=SchedPost(action="delete", post_id=post_id).pack())],
            [InlineKeyboardButton(text="📋 Ro‘yxatga qaytish", callback_data=SchedMenu(action="list").pack())],
        ]
    )


def scheduled_confirm_delete_kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha, o‘chirilsin", callback_data=SchedPost(action="confirmdel", post_id=post_id).pack())],
            [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data=SchedPost(action="view", post_id=post_id).pack())],
        ]
    )


# --- admin-management keyboards ----------------------------------------------

def admins_kb(rows_data: list[tuple[int, str, bool]]) -> InlineKeyboardMarkup:
    """rows_data: list of (user_id, label, is_primary). Primary admins (from
    ADMIN_IDS) are shown with a star and can't be removed."""
    rows = []
    for user_id, label, is_primary in rows_data:
        if is_primary:
            rows.append([InlineKeyboardButton(text=f"⭐ {label}"[:64], callback_data=AdminMgmt(action="back").pack())])
        else:
            rows.append([
                InlineKeyboardButton(text=label[:56], callback_data=AdminMgmt(action="back").pack()),
                InlineKeyboardButton(text="🗑", callback_data=AdminMgmt(action="remove", user_id=user_id).pack()),
            ])
    rows.append([InlineKeyboardButton(text="➕ Admin qo‘shish", callback_data=AdminMgmt(action="add").pack())])
    rows.append([InlineKeyboardButton(text="🔙 Menyu", callback_data=AdminMenu(action="menu").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_remove_confirm_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha, olib tashlansin", callback_data=AdminMgmt(action="confirmrm", user_id=user_id).pack())],
            [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data=AdminMgmt(action="back").pack())],
        ]
    )
