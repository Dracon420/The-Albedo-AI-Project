"""
perf.py — lightweight per-turn timing instrumentation for the Albedo pipeline.

Zero external deps, thread-safe, negligible overhead. Use it to find where a
turn actually spends its time (retrieval / web / wiki / LLM) instead of guessing.

Usage
-----
    from albedo import perf

    turn = perf.Turn(query)
    try:
        with turn.stage("rag"):
            chunks = search_memory(query)
        with turn.stage("llm"):
            answer = bridge_chat(prompt)
        return answer
    finally:
        turn.finish(route="standand-rag")

The last N turns are kept in memory and exposed via ``get_recent()`` so the
Tactical Drawer can show a live latency breakdown. Each turn also prints a
one-line ``[perf]`` summary to the console/log.
"""
from __future__ import annotations

import threading
import time
from collections import deque

_lock = threading.Lock()
_recent: "deque[dict]" = deque(maxlen=50)


class _Stage:
    """Context manager that records one named stage's wall-clock duration."""

    __slots__ = ("_turn", "_name", "_t0")

    def __init__(self, turn: "Turn", name: str) -> None:
        self._turn = turn
        self._name = name
        self._t0 = 0.0

    def __enter__(self) -> "_Stage":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> None:
        self._turn.add(self._name, (time.perf_counter() - self._t0) * 1000.0)


class Turn:
    """One pipeline turn. Collects named stage timings + a grand total."""

    __slots__ = ("label", "stages", "_t0", "_finished")

    def __init__(self, label: str = "") -> None:
        self.label = (label or "")[:60]
        self.stages: list[tuple[str, float]] = []
        self._t0 = time.perf_counter()
        self._finished = False

    def stage(self, name: str) -> _Stage:
        return _Stage(self, name)

    def add(self, name: str, ms: float) -> None:
        self.stages.append((name, round(ms, 1)))

    def finish(self, route: str = "") -> dict:
        """Record the total, store the turn, and log a one-line summary."""
        if self._finished:
            return {}
        self._finished = True
        total = (time.perf_counter() - self._t0) * 1000.0
        rec = {
            "label": self.label,
            "route": route or "?",
            "total_ms": round(total, 1),
            "stages": list(self.stages),
            "ts": time.time(),
        }
        with _lock:
            _recent.append(rec)
        breakdown = "  ".join(f"{n}={ms:.0f}ms" for n, ms in self.stages)
        print(f"[perf] {rec['route']}: total={total:.0f}ms  {breakdown}".rstrip())
        return rec


def get_recent(n: int = 20) -> list[dict]:
    """Most recent turn timings (newest last). Safe to call from any thread."""
    with _lock:
        items = list(_recent)
    return items[-n:]


def clear() -> None:
    with _lock:
        _recent.clear()
