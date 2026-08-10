import re

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from bot import admins
from bot.broadcast import broadcast_copy
from bot.config import settings
from bot.filters import IsAdmin
from bot.formatting import format_store_admin
from bot.keyboards import (
    PAGE_SIZE,
    WEEKDAY_NAMES,
    AdminField,
    AdminMenu,
    AdminMgmt,
    AdminPage,
    AdminStore,
    BroadcastCB,
    SchedDay,
    SchedMenu,
    SchedPick,
    SchedPost,
    admin_confirm_delete_kb,
    admin_list_kb,
    admin_menu_kb,
    admin_remove_confirm_kb,
    admin_store_kb,
    admins_kb,
    broadcast_confirm_kb,
    schedule_days_kb,
    schedule_menu_kb,
    schedule_pick_day_kb,
    scheduled_confirm_delete_kb,
    scheduled_list_kb,
    scheduled_post_kb,
)
from bot import geo
from bot import repository as repo
from bot.states import AddAdmin, AddPost, AddStore, Broadcast, EditStore

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

# Admins paste a map link instead of sharing a live location — bots can only
# share their *own* location, and copy-pasting a Google Maps link is what the
# store owners actually send.
_LOCATION_PROMPT = (
    "📍 Do‘kon joylashuvining <b>havolasini</b> yuboring.\n\n"
    "Google Maps’da nuqtani belgilab, «Ulashish → Havolani nusxalash» qiling "
    "va shu yerga tashlang. <code>41.311081, 69.240562</code> ko‘rinishidagi "
    "koordinatani ham qabul qilamiz."
)
_LOCATION_INVALID = (
    "❌ Havoladan koordinata topilmadi. To‘liq Google Maps havolasini "
    "(masalan <code>https://maps.app.goo.gl/…</code> yoki <code>…/@41.31,69.24…</code>) "
    "yoki <code>lat, lon</code> ko‘rinishidagi koordinatani yuboring."
)


def _col(field: str) -> str:
    return FIELD_COLUMN.get(field, field)


def _clean(text: str) -> str | None:
    text = (text or "").strip()
    return None if text.lower() in _SKIP else text


# --- entry point -------------------------------------------------------------

async def _menu_text() -> str:
    stores = await repo.count_stores()
    total_users, active_users = await repo.count_users()
    online_10m = await repo.count_active_within(10)
    active_today = await repo.count_active_within(24 * 60)
    active_week = await repo.count_active_within(7 * 24 * 60)
    return (
        "🛠 <b>Admin panel</b>\n"
        f"📚 Do‘konlar: <b>{stores}</b>\n"
        f"👥 Foydalanuvchilar: <b>{total_users}</b> (obuna: {active_users})\n"
        "\n"
        "🟢 <b>Faollik</b>\n"
        f"• Oxirgi 10 daqiqada: <b>{online_10m}</b>\n"
        f"• Bugun: <b>{active_today}</b>\n"
        f"• Bu hafta: <b>{active_week}</b>"
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
        return
    if callback_data.action == "schedule":
        await state.clear()
        await callback.message.answer(await _schedule_menu_text(), reply_markup=schedule_menu_kb())
        return
    if callback_data.action == "admins":
        await state.clear()
        text, kb = await _admins_view(callback.from_user.id)
        await callback.message.answer(text, reply_markup=kb)


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
        await callback.message.answer(_LOCATION_PROMPT, reply_markup=ReplyKeyboardRemove())
    else:
        label = FIELD_LABELS[callback_data.field]
        await callback.message.answer(
            f"Yangi <b>{label}</b>ni kiriting (bo‘sh qoldirish uchun «-»):",
            reply_markup=ReplyKeyboardRemove(),
        )


@router.message(EditStore.value, F.text)
async def on_edit_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data["field"]
    if field == "location":
        coords = await geo.coords_from_link(message.text)
        if coords is None:
            await message.answer(_LOCATION_INVALID)
            return
        lat, lon = coords
        await repo.update_store(data["store_id"], latitude=lat, longitude=lon)
        await state.clear()
        store = await repo.get_store_by_id(data["store_id"])
        await message.answer(
            f"✅ Joylashuv yangilandi: <code>{lat:.6f}, {lon:.6f}</code>",
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.answer(format_store_admin(store), reply_markup=admin_store_kb(store.id))
        return

    value = _clean(message.text)
    if field == "name" and not value:
        await message.answer("Nom bo‘sh bo‘lishi mumkin emas. Qaytadan kiriting:")
        return
    if field == "phone" and (not value or sum(c.isdigit() for c in value) < 7):
        await message.answer(
            "❌ Telefon raqami majburiy. To‘g‘ri raqam kiriting "
            "(masalan: +998 90 123 45 67):"
        )
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
    await message.answer(_LOCATION_PROMPT, reply_markup=ReplyKeyboardRemove())


@router.message(AddStore.location, F.text)
async def add_location(message: Message, state: FSMContext) -> None:
    coords = await geo.coords_from_link(message.text)
    if coords is None:
        await message.answer(_LOCATION_INVALID)
        return
    lat, lon = coords
    await state.update_data(lat=lat, lon=lon)
    await state.set_state(AddStore.phone)
    await message.answer(
        f"✅ Koordinata olindi: <code>{lat:.6f}, {lon:.6f}</code>\n\n"
        "☎️ <b>Telefon</b> raqamini kiriting (masalan: +998 90 123 45 67):",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(AddStore.location)
async def add_location_invalid(message: Message) -> None:
    await message.answer(_LOCATION_INVALID)


@router.message(AddStore.phone, F.text)
async def add_phone(message: Message, state: FSMContext) -> None:
    phone = (message.text or "").strip()
    # Phone is required — a store with no way to call it is useless. Insist on
    # something that actually contains digits.
    if not phone or phone in _SKIP or sum(c.isdigit() for c in phone) < 7:
        await message.answer(
            "❌ Telefon raqami majburiy. Iltimos, to‘g‘ri raqam kiriting "
            "(masalan: +998 90 123 45 67):"
        )
        return
    await state.update_data(phone=phone)
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


# --- scheduled weekly posts --------------------------------------------------

async def _schedule_menu_text() -> str:
    days = await repo.get_enabled_weekdays()
    day_str = ", ".join(WEEKDAY_NAMES[d] for d in sorted(days)) if days else "hali tanlanmagan"
    count = await repo.count_scheduled_posts()
    return (
        "📅 <b>Rejalashtirilgan postlar</b>\n"
        f"🗓 Faol kunlar: <b>{day_str}</b>\n"
        f"📋 Postlar soni: <b>{count}</b>"
    )


def _parse_hhmm(raw: str) -> str | None:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", raw or "")
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def _post_text(post) -> str:
    last = post.last_sent_on.isoformat() if post.last_sent_on else "hali yuborilmagan"
    return (
        f"📅 <b>Rejalashtirilgan post #{post.id}</b>\n"
        f"🗓 Kun: <b>{WEEKDAY_NAMES[post.weekday]}</b>\n"
        f"🕒 Vaqt: <b>{post.send_time}</b>\n"
        f"📝 Matn: {post.preview or '—'}\n"
        f"📤 Oxirgi yuborilgan: {last}"
    )


@router.callback_query(SchedMenu.filter())
async def on_sched_menu(callback: CallbackQuery, callback_data: SchedMenu, state: FSMContext) -> None:
    await callback.answer()
    action = callback_data.action

    if action == "menu":
        await state.clear()
        await callback.message.answer(await _schedule_menu_text(), reply_markup=schedule_menu_kb())
        return

    if action == "days":
        days = await repo.get_enabled_weekdays()
        await callback.message.answer(
            "🗓 Post yuboriladigan kunlarni tanlang (bosib yoqing / o‘chiring):",
            reply_markup=schedule_days_kb(days),
        )
        return

    if action == "list":
        posts = await repo.list_scheduled_posts()
        if not posts:
            await callback.message.answer("Hozircha rejalashtirilgan post yo‘q.", reply_markup=schedule_menu_kb())
            return
        await callback.message.answer("📋 Rejalashtirilgan postlar:", reply_markup=scheduled_list_kb(posts))
        return

    if action == "add":
        days = await repo.get_enabled_weekdays()
        if not days:
            await callback.message.answer(
                "Avval «🗓 Kunlarni tanlash» orqali kamida bitta kun tanlang.",
                reply_markup=schedule_menu_kb(),
            )
            return
        await state.clear()
        await callback.message.answer(
            "Qaysi kunga post rejalashtiramiz?",
            reply_markup=schedule_pick_day_kb(days),
        )


@router.callback_query(SchedDay.filter())
async def on_sched_day_toggle(callback: CallbackQuery, callback_data: SchedDay) -> None:
    days = await repo.toggle_weekday(callback_data.weekday)
    on = callback_data.weekday in days
    await callback.answer(f"{WEEKDAY_NAMES[callback_data.weekday]}: {'yoqildi' if on else 'o‘chirildi'}")
    try:
        await callback.message.edit_reply_markup(reply_markup=schedule_days_kb(days))
    except Exception:  # noqa: BLE001 — markup unchanged/expired is harmless
        pass


@router.callback_query(SchedPick.filter())
async def on_sched_pick_day(callback: CallbackQuery, callback_data: SchedPick, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AddPost.time)
    await state.update_data(weekday=callback_data.weekday)
    await callback.message.answer(
        f"🕒 <b>{WEEKDAY_NAMES[callback_data.weekday]}</b> kuni post nechida yuborilsin?\n"
        "Vaqtni <b>HH:MM</b> ko‘rinishida kiriting (masalan: 09:30).",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(AddPost.time, F.text)
async def on_sched_time(message: Message, state: FSMContext) -> None:
    hhmm = _parse_hhmm(message.text)
    if not hhmm:
        await message.answer("Vaqt formati noto‘g‘ri. <b>HH:MM</b> ko‘rinishida kiriting (masalan: 18:00).")
        return
    await state.update_data(send_time=hhmm)
    await state.set_state(AddPost.content)
    await message.answer(
        "Endi yubormoqchi bo‘lgan <b>postni</b> yuboring "
        "(matn, rasm, rasm + izoh — istalgan ko‘rinishda)."
    )


@router.message(AddPost.content)
async def on_sched_content(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    preview = ((message.text or message.caption or "post").strip().replace("\n", " "))[:120]
    post = await repo.create_scheduled_post(
        weekday=data["weekday"],
        send_time=data["send_time"],
        from_chat_id=message.chat.id,
        message_id=message.message_id,
        preview=preview,
    )
    await state.clear()
    await message.answer(
        "✅ <b>Post rejalashtirildi!</b>\n"
        f"🗓 {WEEKDAY_NAMES[post.weekday]} · 🕒 {post.send_time}\n"
        "Ushbu kun kelganda barcha faol foydalanuvchilarga yuboriladi."
    )
    await message.answer(await _schedule_menu_text(), reply_markup=schedule_menu_kb())


@router.callback_query(SchedPost.filter(F.action == "view"))
async def on_sched_post_view(callback: CallbackQuery, callback_data: SchedPost) -> None:
    await callback.answer()
    post = await repo.get_scheduled_post(callback_data.post_id)
    if post is None:
        await callback.message.answer("Post topilmadi.")
        return
    await callback.message.answer(_post_text(post), reply_markup=scheduled_post_kb(post.id))


@router.callback_query(SchedPost.filter(F.action == "delete"))
async def on_sched_post_delete(callback: CallbackQuery, callback_data: SchedPost) -> None:
    await callback.answer()
    await callback.message.answer(
        "⚠️ Ushbu rejalashtirilgan post o‘chirilsinmi?",
        reply_markup=scheduled_confirm_delete_kb(callback_data.post_id),
    )


@router.callback_query(SchedPost.filter(F.action == "confirmdel"))
async def on_sched_post_confirmdel(callback: CallbackQuery, callback_data: SchedPost) -> None:
    ok = await repo.delete_scheduled_post(callback_data.post_id)
    await callback.answer("O‘chirildi" if ok else "Topilmadi", show_alert=True)
    posts = await repo.list_scheduled_posts()
    if posts:
        await callback.message.answer("📋 Rejalashtirilgan postlar:", reply_markup=scheduled_list_kb(posts))
    else:
        await callback.message.answer(await _schedule_menu_text(), reply_markup=schedule_menu_kb())


# --- admin management (add / remove admins) ---------------------------------

async def _admin_label(user_id: int) -> str:
    user = await repo.get_user(user_id)
    name = (user.first_name or user.username) if user else None
    return f"{name} · {user_id}" if name else str(user_id)


async def _admins_rows() -> list[tuple[int, str, bool]]:
    primary = settings.admin_id_set
    db_only = admins.all_admin_ids() - primary
    rows: list[tuple[int, str, bool]] = []
    for uid in sorted(primary):
        rows.append((uid, await _admin_label(uid), True))
    for uid in sorted(db_only):
        rows.append((uid, await _admin_label(uid), False))
    return rows


async def _admins_text(actor_id: int | None = None) -> str:
    total = len(admins.all_admin_ids())
    lines = [
        "👑 <b>Adminlar</b>",
        f"Jami: <b>{total}</b> ta",
        "",
        "⭐ — asosiy admin (o‘chirib bo‘lmaydi).",
    ]
    if actor_id is not None and admins.is_primary_admin(actor_id):
        lines.append("Yangi admin qo‘shish uchun «➕ Admin qo‘shish» tugmasini bosing.")
    else:
        lines.append("ℹ️ Yangi admin qo‘shish faqat asosiy adminga ruxsat etilgan.")
    return "\n".join(lines)


async def _admins_view(actor_id: int):
    """(text, keyboard) for the admins screen — the add button and hint only
    appear for the primary admin, who alone may add new admins."""
    can_add = admins.is_primary_admin(actor_id)
    return await _admins_text(actor_id), admins_kb(await _admins_rows(), can_add=can_add)


def _extract_user_id(message: Message) -> int | None:
    """Get a target user id from a numeric text, forwarded message, or contact."""
    if message.contact and message.contact.user_id:
        return message.contact.user_id
    fwd = getattr(message, "forward_from", None)
    if fwd:
        return fwd.id
    origin = getattr(message, "forward_origin", None)
    if origin and getattr(origin, "sender_user", None):
        return origin.sender_user.id
    if message.text and message.text.strip().isdigit():
        return int(message.text.strip())
    return None


@router.callback_query(AdminMgmt.filter(F.action == "back"))
async def on_admins_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    text, kb = await _admins_view(callback.from_user.id)
    await callback.message.answer(text, reply_markup=kb)


@router.callback_query(AdminMgmt.filter(F.action == "add"))
async def on_admin_add_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    # Only the primary (super) admin may add new admins.
    if not admins.is_primary_admin(callback.from_user.id):
        await callback.answer("Faqat asosiy admin yangi admin qo‘sha oladi.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AddAdmin.waiting)
    await callback.message.answer(
        "➕ <b>Yangi admin</b>\n\n"
        "Yangi adminni qo‘shish uchun quyidagilardan birini yuboring:\n"
        "• uning <b>Telegram ID</b> raqamini,\n"
        "• undan <b>forward</b> qilingan xabarni,\n"
        "• yoki uning <b>kontaktini</b>.\n\n"
        "Bekor qilish uchun /cancel.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(AddAdmin.waiting)
async def on_admin_add(message: Message, state: FSMContext) -> None:
    # Defense in depth: even if someone reaches this state, only the primary
    # admin is allowed to actually add an admin.
    if not admins.is_primary_admin(message.from_user.id):
        await state.clear()
        await message.answer("Faqat asosiy admin yangi admin qo‘sha oladi.")
        return

    user_id = _extract_user_id(message)
    if user_id is None:
        await message.answer(
            "Foydalanuvchini aniqlay olmadim. Raqamli ID, forward xabar yoki "
            "kontakt yuboring (yoki /cancel)."
        )
        return

    if admins.is_admin(user_id):
        await state.clear()
        who = "asosiy admin" if admins.is_primary_admin(user_id) else "admin"
        await message.answer(f"Bu foydalanuvchi allaqachon {who}.")
        text, kb = await _admins_view(message.from_user.id)
        await message.answer(text, reply_markup=kb)
        return

    await admins.add(user_id, added_by=message.from_user.id)
    await state.clear()
    await message.answer(f"✅ Yangi admin qo‘shildi: <b>{await _admin_label(user_id)}</b>")
    text, kb = await _admins_view(message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(AdminMgmt.filter(F.action == "remove"))
async def on_admin_remove_prompt(callback: CallbackQuery, callback_data: AdminMgmt) -> None:
    await callback.answer()
    if admins.is_primary_admin(callback_data.user_id):
        await callback.answer("Asosiy adminni o‘chirib bo‘lmaydi.", show_alert=True)
        return
    await callback.message.answer(
        f"⚠️ <b>{await _admin_label(callback_data.user_id)}</b> adminlikdan olib tashlansinmi?",
        reply_markup=admin_remove_confirm_kb(callback_data.user_id),
    )


@router.callback_query(AdminMgmt.filter(F.action == "confirmrm"))
async def on_admin_remove_confirm(callback: CallbackQuery, callback_data: AdminMgmt) -> None:
    if admins.is_primary_admin(callback_data.user_id):
        await callback.answer("Asosiy adminni o‘chirib bo‘lmaydi.", show_alert=True)
        return
    ok = await admins.remove(callback_data.user_id)
    await callback.answer("Olib tashlandi" if ok else "Topilmadi", show_alert=True)
    text, kb = await _admins_view(callback.from_user.id)
    await callback.message.answer(text, reply_markup=kb)
