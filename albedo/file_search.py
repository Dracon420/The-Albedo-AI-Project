"""
file_search.py — find files by name/topic using the dream-cycle file catalog
(ChromaDB 'file_catalog'), with a filesystem glob fallback. Caches the last
result set so the file-search popup can display it.
"""
from __future__ import annotations

from pathlib import Path

_last: list[dict] = []


def _from_catalog(query: str, limit: int) -> list[dict]:
    try:
        import chromadb
        root = Path(__file__).resolve().parent.parent
        client = chromadb.PersistentClient(path=str(root / "chroma_db"))
        col = client.get_or_create_collection("file_catalog")
        if col.count() == 0:
            return []
        res = col.query(query_texts=[query], n_results=min(limit, 40))
        metas = (res.get("metadatas") or [[]])[0]
        out = []
        for m in metas:
            if not m:
                continue
            out.append({"name": m.get("name", ""), "path": m.get("path", ""),
                        "parent": m.get("parent", ""), "size_kb": m.get("size_kb", 0)})
        return out
    except Exception:
        return []


def _from_glob(query: str, limit: int) -> list[dict]:
    q = query.lower()
    out: list[dict] = []
    roots = [Path.home() / d for d in ("Desktop", "Documents", "Downloads", "Pictures")]
    for r in roots:
        if not r.exists():
            continue
        try:
            for p in r.rglob("*"):
                if not p.is_file():
                    continue
                if q in p.name.lower():
                    try:
                        kb = round(p.stat().st_size / 1024, 1)
                    except Exception:
                        kb = 0
                    out.append({"name": p.name, "path": str(p),
                                "parent": str(p.parent), "size_kb": kb})
                    if len(out) >= limit:
                        return out
        except Exception:
            pass
    return out


def search(query: str, limit: int = 20) -> list[dict]:
    global _last
    query = (query or "").strip()
    if not query:
        _last = []
        return []
    res = _from_catalog(query, limit) or _from_glob(query, limit)
    _last = res[:limit]
    return _last


def last() -> list[dict]:
    return list(_last)
