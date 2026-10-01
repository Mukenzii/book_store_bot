"""Feature flags: ship new features to testers first, then release to everyone.

Each feature is in one of two stages:
  * "test" — visible only to users who switched test mode on for themselves
             (a super-admin button in /admin → 🧪 Test rejimi);
  * "live" — visible to everyone.

New features start in "test". Stages and the tester list live in the settings
table and are cached in memory (read on every update, like the admin cache).

To gate a new feature: add it to FEATURES, then check
`features.enabled("<key>", user_id)` wherever it shows up.
"""

from bot import repository as repo

TEST = "test"
LIVE = "live"

# key -> human-readable name shown in the test-mode panel.
FEATURES: dict[str, str] = {
    "store_books": "Do‘kon egalari kitoblari",
}

_TESTERS_KEY = "tester_ids"

_stages: dict[str, str] = {}
_testers: set[int] = set()
# Role a tester is acting as: missing = regular user; "owner:<store_id>" =
# owner of that store (lets them test owner features with no phone match).
_roles: dict[int, str] = {}


def _role_key(user_id: int) -> str:
    return f"test_role:{user_id}"


def _stage_key(key: str) -> str:
    return f"feature:{key}"


async def load() -> None:
    global _testers
    for key in FEATURES:
        _stages[key] = await repo.get_setting(_stage_key(key), TEST) or TEST
    raw = await repo.get_setting(_TESTERS_KEY, "") or ""
    _testers = {int(x) for x in raw.split(",") if x.strip().isdigit()}
    for uid in _testers:
        role = await repo.get_setting(_role_key(uid), "") or ""
        if role:
            _roles[uid] = role


def stage(key: str) -> str:
    return _stages.get(key, TEST)


def is_tester(user_id: int) -> bool:
    return user_id in _testers


def any_in_test() -> bool:
    """True while at least one feature is still being tested."""
    return any(stage(k) == TEST for k in FEATURES)


def in_test_env(user_id: int) -> bool:
    """Tester AND something is still in testing. Once every feature is released
    the test environment (Test do'kon etc.) disappears, even for testers."""
    return user_id in _testers and any_in_test()


def enabled(key: str, user_id: int) -> bool:
    if stage(key) == LIVE:
        return True
    return user_id in _testers


async def set_stage(key: str, new_stage: str) -> None:
    _stages[key] = new_stage
    await repo.set_setting(_stage_key(key), new_stage)


async def set_tester(user_id: int, on: bool) -> None:
    if on:
        _testers.add(user_id)
    else:
        _testers.discard(user_id)
    await repo.set_setting(_TESTERS_KEY, ",".join(str(i) for i in sorted(_testers)))


def acting_owner_store(user_id: int) -> int | None:
    """Store id the tester is impersonating the owner of, or None (also None
    once nothing is left in testing)."""
    if not in_test_env(user_id):
        return None
    role = _roles.get(user_id, "")
    if role.startswith("owner:") and role[6:].isdigit():
        return int(role[6:])
    return None


async def set_owner_role(user_id: int, store_id: int | None) -> None:
    """Act as owner of `store_id` (turns test mode on), or None = back to user."""
    if store_id is None:
        _roles.pop(user_id, None)
        await repo.set_setting(_role_key(user_id), "")
        return
    _roles[user_id] = f"owner:{store_id}"
    await repo.set_setting(_role_key(user_id), _roles[user_id])
    if user_id not in _testers:
        await set_tester(user_id, True)
