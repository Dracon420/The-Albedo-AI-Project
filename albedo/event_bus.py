"""
event_bus.py — tiny in-process pub/sub for live agent/team/RAG activity.

Backend producers (agent.py, agent_team.py, memory.py) call publish(event) when
something interesting happens. The bridge subscribes ONCE at UI start and fans
events out to the JS layer via eel._albedo_event(evt). Front-end consumers
(Brain viz, Team viz, chat) subscribe in JS.

Events are plain JSON-serializable dicts: {"type": str, ...payload}.

Standard event types (extend freely — the bus is type-agnostic):
    team.start    {"goal": str}
    team.plan     {"tasks": [{role,task}, ...]}
    team.critique {"complete": bool, "summary": str, "gaps": [...]}
    team.done     {"ok": bool}
    agent.state   {"role": str, "state": "idle"|"thinking"|"tool"|"done"|"error",
                   "task": str|None}
    tool.call     {"role": str, "name": str, "args": dict}
    tool.result   {"role": str, "name": str, "ok": bool, "summary": str}
    rag.hit       {"query": str, "notes": [{"title": str, "path": str}, ...]}

The bus is best-effort: a slow/broken subscriber NEVER blocks producers (each
delivery wrapped in try/except). Subscriber callbacks should be cheap or push to
their own queue.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

# Bounded history so the bus never grows unbounded if no UI is attached.
_HISTORY_CAP = 500

_lock = threading.Lock()
_subscribers: list[Callable[[dict], None]] = []
_history: deque = deque(maxlen=_HISTORY_CAP)


def subscribe(callback: Callable[[dict], None]) -> None:
    """Register a callback for every future event. Idempotent per callback."""
    with _lock:
        if callback not in _subscribers:
            _subscribers.append(callback)


def unsubscribe(callback: Callable[[dict], None]) -> None:
    with _lock:
        if callback in _subscribers:
            _subscribers.remove(callback)


def publish(event_type: str, **payload: Any) -> dict:
    """
    Publish an event. Never raises. Returns the event dict (useful for tests).
    Each subscriber is called in a try/except so one bad subscriber doesn't
    break the others or the producer.
    """
    evt = {"type": event_type, "ts": time.time(), **payload}
    with _lock:
        _history.append(evt)
        subs = list(_subscribers)
    for cb in subs:
        try:
            cb(evt)
        except Exception as exc:                                    # noqa: BLE001
            print(f"[event_bus] subscriber error ({event_type}): {exc}")
    return evt


def history(limit: int = 200) -> list[dict]:
    """Return the most recent `limit` events (oldest first). For late-joining UIs."""
    with _lock:
        items = list(_history)
    return items[-limit:]


def clear_history() -> None:
    with _lock:
        _history.clear()
