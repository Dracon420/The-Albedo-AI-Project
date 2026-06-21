"""
cache.py — tiny thread-safe TTL cache for expensive external tool calls.

Used to memoize web search / Wikipedia / Wolfram results so repeated or
in-session-similar queries skip the network round-trip entirely. Zero deps.

    from albedo.cache import ttl_cache

    @ttl_cache(ttl_seconds=600, key_fn=lambda q, *a, **k: q.strip().lower())
    def web_search(query): ...

Falsy results (empty list / None / "") are NOT cached, so a transient failure
won't be remembered as "no result".
"""
from __future__ import annotations

import functools
import hashlib
import threading
import time


class TTLCache:
    def __init__(self, ttl_seconds: float = 900, maxsize: int = 256) -> None:
        self.ttl = float(ttl_seconds)
        self.maxsize = int(maxsize)
        self._d: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str):
        now = time.time()
        with self._lock:
            item = self._d.get(key)
            if item is None:
                self.misses += 1
                return None, False
            expires, value = item
            if expires < now:
                self._d.pop(key, None)
                self.misses += 1
                return None, False
            self.hits += 1
            return value, True

    def set(self, key: str, value) -> None:
        with self._lock:
            if len(self._d) >= self.maxsize and key not in self._d:
                # evict the entry that expires soonest
                oldest = min(self._d.items(), key=lambda kv: kv[1][0])[0]
                self._d.pop(oldest, None)
            self._d[key] = (time.time() + self.ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()

    def stats(self) -> dict:
        with self._lock:
            return {"size": len(self._d), "hits": self.hits, "misses": self.misses}


def _default_key(args, kwargs) -> str:
    raw = repr(args) + "|" + repr(sorted(kwargs.items()))
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()


def ttl_cache(ttl_seconds: float = 900, maxsize: int = 256, key_fn=None):
    """Decorator: memoize a function's truthy return values for ttl_seconds."""
    def deco(fn):
        cache = TTLCache(ttl_seconds, maxsize)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                key = key_fn(*args, **kwargs) if key_fn else _default_key(args, kwargs)
            except Exception:
                return fn(*args, **kwargs)   # un-keyable call → don't cache
            value, hit = cache.get(key)
            if hit:
                return value
            value = fn(*args, **kwargs)
            if value:                        # never cache empty/error results
                cache.set(key, value)
            return value

        wrapper.cache = cache                # expose for stats / clear
        return wrapper
    return deco
