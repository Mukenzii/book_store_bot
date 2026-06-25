from html import escape

from bot.models import Store
from bot.repository import StoreWithDistance


def format_store_details(store: StoreWithDistance) -> str:
    """Build the HTML message shown once a user picks a store."""
    lines = [f"📚 <b>{escape(store.name)}</b>", ""]
    if store.address:
        lines.append(f"📍 <b>Manzil:</b> {escape(store.address)}")
    lines.append(f"🧭 <b>Masofa:</b> sizdan {store.distance_km:.1f} km uzoqlikda")

    if store.working_hours:
        lines.append(f"🕒 <b>Ish vaqti:</b> {escape(store.working_hours)}")
    if store.phone:
        lines.append(f"☎️ <b>Telefon:</b> {escape(store.phone)}")
    if store.description:
        lines.append("")
        lines.append(escape(store.description))

    return "\n".join(lines)


def format_store_admin(store: Store) -> str:
    """Detailed admin view of a store (no distance)."""
    def val(x) -> str:
        return escape(str(x)) if x not in (None, "") else "—"

    return (
        f"🏪 <b>#{store.id} · {escape(store.name)}</b>\n\n"
        f"📍 <b>Manzil:</b> {val(store.address)}\n"
        f"🕒 <b>Ish vaqti:</b> {val(store.working_hours)}\n"
        f"☎️ <b>Telefon:</b> {val(store.phone)}\n"
        f"📝 <b>Tavsif:</b> {val(store.description)}\n"
        f"🧭 <b>Koordinatalar:</b> {store.latitude:.6f}, {store.longitude:.6f}"
    )
