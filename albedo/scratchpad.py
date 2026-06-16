"""
scratchpad.py — Albedo working memory / persistent agent scratchpad.

The team architecture is otherwise stateless: each run_team() / run_agent() call
starts fresh. This module provides a SHARED scratchpad agents can write to and
read from across runs and sessions — short notes, learned facts, in-progress
context. Long-term semantic memory still lives in ChromaDB (memory.py); this
is the working / episodic layer.

Storage: JSON file at project root (`scratchpad.json`), gitignored, small.
Cap: keeps the most recent 200 notes to stay bounded.

Public API:
    note(text, tags=None, source="agent")      -> dict   (the saved entry)
    recall(query=None, tag=None, limit=10)     -> list[dict]
    forget(note_id)                             -> bool
    clear()                                     -> int   (count cleared)
    all_tags()                                  -> list[str]
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
_FILE = _ROOT / "scratchpad.json"
_CAP = 200
_lock = threading.Lock()


def _load() -> list[dict]:
    try:
        if _FILE.exists():
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save(notes: list[dict]) -> None:
    try:
        _FILE.write_text(json.dumps(notes[-_CAP:], indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[scratchpad] write failed: {exc}")


def note(text: str, tags: Optional[list[str]] = None, source: str = "agent") -> dict:
    """Save a short note to the scratchpad. Returns the saved entry."""
    entry = {
        "id":     uuid.uuid4().hex[:10],
        "ts":     time.time(),
        "source": source,
        "tags":   list(tags) if tags else [],
        "text":   (text or "").strip(),
    }
    with _lock:
        notes = _load()
        notes.append(entry)
        _save(notes)
    return entry


def recall(query: Optional[str] = None, tag: Optional[str] = None,
           limit: int = 10) -> list[dict]:
    """Return matching notes (most-recent first). Substring match on text + tags."""
    with _lock:
        notes = list(_load())
    notes.reverse()
    q = (query or "").lower().strip()
    out = []
    for n in notes:
        if tag and tag not in (n.get("tags") or []):
            continue
        if q and q not in (n.get("text") or "").lower() and \
           not any(q in t.lower() for t in (n.get("tags") or [])):
            continue
        out.append(n)
        if len(out) >= max(1, int(limit or 10)):
            break
    return out


def forget(note_id: str) -> bool:
    with _lock:
        notes = _load()
        kept = [n for n in notes if n.get("id") != note_id]
        if len(kept) == len(notes):
            return False
        _save(kept)
        return True


def clear() -> int:
    with _lock:
        n = len(_load())
        _save([])
    return n


def all_tags() -> list[str]:
    with _lock:
        notes = _load()
    tags = set()
    for n in notes:
        for t in (n.get("tags") or []):
            tags.add(t)
    return sorted(tags)


def size() -> int:
    with _lock:
        return len(_load())
