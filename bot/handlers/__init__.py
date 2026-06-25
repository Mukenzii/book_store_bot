from aiogram import Router

from bot.handlers import admin, start, location, store


def get_root_router() -> Router:
    """Aggregate every feature router into one for the dispatcher.

    Admin is included first so its state-filtered handlers (add/edit flows)
    intercept admin input before the public location/text handlers can.
    """
    router = Router()
    router.include_router(admin.router)
    router.include_router(start.router)
    router.include_router(location.router)
    router.include_router(store.router)
    return router
