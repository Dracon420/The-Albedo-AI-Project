"""
semantic_cache.py — embedding-keyed answer cache for repeated KNOWLEDGE questions.

When the user asks a near-duplicate of a recent question, return the prior
answer instantly instead of calling the LLM again. Reuses the prewarmed
all-MiniLM-L6-v2 model (via memory.embed_query) to embed the query.

Safety (this is an assistant that also answers live/system questions):
  • VOLATILE queries are never cached or served (today / now / cpu / price / …)
  • Only answers that used NO tools are stored (a tool answer reflects live
    state — caching it would go stale). The caller enforces this on store().
  • High cosine-similarity threshold + short TTL + small bound.

API:
    lookup(query) -> answer str | None
    store(query, answer)
    stats() -> dict
"""
from __future__ import annotations

import math
import re
import threading
import time

_THRESHOLD = 0.90      # cosine similarity to treat two questions as "the same".
# Calibrated empirically: true rephrasings score 0.91–1.0; genuinely different
# questions (capital of France vs Germany, capital vs population) top out ~0.71.
# 0.90 catches casing/contraction rephrases with a ~19pt safety margin.
_TTL = 1800.0          # 30 min
_MAX = 80

# Never cache/serve answers to time- or system-state-sensitive questions.
_VOLATILE = re.compile(
    r"\b(today|tonight|now|current|currently|latest|recent|just|"
    r"weather|price|stock|news|score|time|date|when is|uptime|battery|"
    r"running|cpu|ram|gpu|vram|disk|memory|process|processes|temperature|"
    r"temp|usage|load|free space|drained|draining)\b",
    re.IGNORECASE,
)

_lock = threading.Lock()
_entries: list[dict] = []   # {vec, norm, query, answer, ts}
_hits = 0
_misses = 0


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v)) or 1.0


def _cos(a: list[float], an: float, b: list[float], bn: float) -> float:
    return sum(x * y for x, y in zip(a, b)) / (an * bn)


def _is_volatile(q: str) -> bool:
    return bool(_VOLATILE.search(q or ""))


def lookup(query: str) -> str | None:
    """Return a cached answer for a near-duplicate prior question, or None."""
    global _hits, _misses
    q = (query or "").strip()
    if len(q) < 8 or _is_volatile(q):
        return None
    from memory import embed_query
    v = embed_query(q)
    if not v:
        return None
    vn = _norm(v)
    now = time.time()
    with _lock:
        best = None
        best_sim = 0.0
        for e in _entries:
            if now - e["ts"] > _TTL:
                continue
            s = _cos(v, vn, e["vec"], e["norm"])
            if s > best_sim:
                best_sim = s
                best = e
        if best is not None and best_sim >= _THRESHOLD:
            _hits += 1
            return best["answer"]
        _misses += 1
    return None


def store(query: str, answer: str) -> None:
    """Cache a knowledge answer. No-op for volatile/empty inputs."""
    q = (query or "").strip()
    a = (answer or "").strip()
    if len(q) < 8 or not a or _is_volatile(q):
        return
    from memory import embed_query
    v = embed_query(q)
    if not v:
        return
    now = time.time()
    with _lock:
        # drop expired
        _entries[:] = [e for e in _entries if now - e["ts"] <= _TTL]
        _entries.append({"vec": v, "norm": _norm(v), "query": q,
                         "answer": a, "ts": now})
        if len(_entries) > _MAX:
            _entries.pop(0)


def stats() -> dict:
    with _lock:
        return {"size": len(_entries), "hits": _hits, "misses": _misses}


def clear() -> None:
    with _lock:
        _entries.clear()
