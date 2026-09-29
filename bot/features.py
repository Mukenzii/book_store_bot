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
    "store_books": "Do‘kon egalari kitoblari (/dokonim + do‘kon kartasidagi kitoblar)",
}

_TESTERS_KEY = "tester_ids"

_stages: dict[str, str] = {}
_testers: set[int] = set()


def _stage_key(key: str) -> str:
    return f"feature:{key}"


async def load() -> None:
    global _testers
    for key in FEATURES:
        _stages[key] = await repo.get_setting(_stage_key(key), TEST) or TEST
    raw = await repo.get_setting(_TESTERS_KEY, "") or ""
    _testers = {int(x) for x in raw.split(",") if x.strip().isdigit()}


def stage(key: str) -> str:
    return _stages.get(key, TEST)


def is_tester(user_id: int) -> bool:
    return user_id in _testers


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
