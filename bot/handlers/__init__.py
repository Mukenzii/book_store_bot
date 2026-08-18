from aiogram import Router

from bot.handlers import admin, ai, start, location, store


def get_root_router() -> Router:
    """Aggregate every feature router into one for the dispatcher.

    Order matters: admin first so its state-filtered flows intercept admin
    input; ai before location so the AI-chat state (and its buttons) catch
    free text before the public 'share your location' text handler does.
    """
    router = Router()
    router.include_router(admin.router)
    router.include_router(ai.router)
    router.include_router(start.router)
    router.include_router(location.router)
    router.include_router(store.router)
    return router
