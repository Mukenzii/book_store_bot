from aiogram import Router

from bot.handlers import admin, ai, books, owner, start, location, store


def get_root_router() -> Router:
    """Aggregate every feature router into one for the dispatcher.

    Order matters: admin first so its state-filtered flows intercept admin
    input; ai before location so the AI-chat state (and its buttons) catch
    free text before the public 'share your location' text handler does.
    """
    router = Router()
    router.include_router(admin.router)
    # books before owner/location: its menu button must not be taken as an
    # owner's typed book title or as stray text.
    router.include_router(books.router)
    router.include_router(ai.router)
    # owner before location so the owner's free-text book-adding state catches
    # input before the public 'share your location' text handler.
    router.include_router(owner.router)
    router.include_router(start.router)
    router.include_router(location.router)
    router.include_router(store.router)
    return router
