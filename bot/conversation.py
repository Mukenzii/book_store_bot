"""Bounded, expiring conversation data stored in aiogram's per-user chat FSM.

History is context, never source evidence. It is intentionally session-local:
Back/new AI session, inactivity, and process restart forget it.
"""
import time

MAX_MESSAGES = 12
MAX_MESSAGE_CHARS = 1200
TTL_SECONDS = 1800


def messages(value):
    return [
        {"role": m["role"], "content": m["content"][:MAX_MESSAGE_CHARS]}
        for m in (value or [])[-MAX_MESSAGES:]
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
    ]


def read(data, now=None):
    now = time.time() if now is None else now
    saved = data.get("ai_conversation") or {}
    if now - saved.get("updated_at", 0) > TTL_SECONDS:
        return {"history": [], "book_title": None, "topic": ""}
    return {"history": messages(saved.get("history")),
            "book_title": saved.get("book_title"), "topic": saved.get("topic", ""),
            "evidence": [x for x in saved.get("evidence", []) if isinstance(x, str)][:3]}


async def remember(state, previous, question, answer, *, book_title=None, topic="", evidence=()):
    history = messages(previous.get("history", []) + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ])
    await state.update_data(ai_conversation={"history": history, "book_title": book_title,
                                            "topic": topic[:500], "evidence": list(evidence)[:3], "updated_at": time.time()})
