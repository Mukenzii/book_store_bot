from aiogram.fsm.state import State, StatesGroup


class StoreSearch(StatesGroup):
    """Tracks where the user is in the find-a-store flow."""

    # Set once the user has shared a location; we keep their coordinates so the
    # "show details" step can recompute distance to the chosen store.
    choosing_store = State()


class AddStore(StatesGroup):
    """Admin flow for creating a new store."""

    name = State()
    location = State()
    phone = State()
    hours = State()


class EditStore(StatesGroup):
    """Admin flow for editing a single field of an existing store."""

    # data carries: store_id, field (and field == 'location' expects a location)
    value = State()


class Broadcast(StatesGroup):
    """Admin flow for sending an announcement to all users."""

    message = State()   # waiting for the admin's content
    confirm = State()   # waiting for the confirm button
