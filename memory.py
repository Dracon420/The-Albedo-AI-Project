"""
memory.py  --  Albedo Obsidian Vault RAG Pipeline

Indexes .md and .txt files from an Obsidian vault into a persistent
ChromaDB collection using the all-MiniLM-L6-v2 local embedding model.
No internet connection required after the model is downloaded once.

Public API
----------
index_obsidian_vault(vault_path)  -- build / rebuild the semantic index
search_memory(query, n_results)   -- retrieve the most relevant chunks

The ChromaDB database is stored at ./albedo_memory_db next to this file.
The collection name is 'obsidian_vault'.

Chunking is done natively (no langchain import at runtime) with a simple
sliding window: 1 000-character chunks, 200-character overlap. Chunks are
upserted so re-indexing is idempotent -- existing chunks are overwritten,
deleted files are not removed (run a fresh index to clean up).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Resolved at call time so a freshly-written .env is picked up without restart.
def _default_vault() -> str:
    from dotenv import load_dotenv
    load_dotenv(override=False)
    return os.getenv("OBSIDIAN_VAULT_PATH", "")
DB_PATH       = str(Path(__file__).parent / "albedo_memory_db")
COLLECTION    = "obsidian_vault"
CHUNK_SIZE    = 1000
CHUNK_OVERLAP = 200

# Singleton embedding function — lazy-loaded on first use to avoid blocking
# at import time if the model file is corrupt or being downloaded.
_EF: "SentenceTransformerEmbeddingFunction | None" = None
_EF_tried = False


def _get_ef() -> "SentenceTransformerEmbeddingFunction | None":
    global _EF, _EF_tried
    if _EF_tried:
        return _EF
    _EF_tried = True
    try:
        import os as _os
        from pathlib import Path as _Path
        _hf_cache = _Path.home() / ".cache" / "huggingface" / "hub"
        _prefix    = "models--sentence-transformers--all-MiniLM-L6-v2"
        _cached    = (
            any(p.name.startswith(_prefix) for p in _hf_cache.iterdir())
            if _hf_cache.exists() else False
        )
        _prev = _os.environ.get("HF_HUB_OFFLINE")
        if _cached:
            _os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            _EF = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        finally:
            if _prev is None:
                _os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                _os.environ["HF_HUB_OFFLINE"] = _prev
        print("[memory] Embedding model loaded (all-MiniLM-L6-v2, CPU).")
    except Exception as exc:
        print(f"[memory] WARNING: embedding model unavailable ({exc}). Search will return empty results.")
        _EF = None
    return _EF


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=DB_PATH)
    return client.get_or_create_collection(
        name=COLLECTION,
        embedding_function=_get_ef(),
    )


def prewarm() -> None:
    """
    Load the embedding model + open the collection + run one throwaway encode
    so the FIRST real RAG search doesn't pay the cold-start.

    Measured cold first query: ~44 s (the initial SentenceTransformer forward
    pass on CPU). Warm queries: ~65 ms. Call this once in a background daemon
    thread at app startup so that latency is absorbed before the user asks
    anything. Safe + idempotent (the embedding fn is a process singleton).
    """
    import time as _time
    t0 = _time.perf_counter()
    try:
        ef = _get_ef()
        if ef is None:
            print("[memory] prewarm skipped — embedding model unavailable.")
            return
        col = _get_collection()
        _ = col.count()
        ef(["warmup"])  # first encode is the expensive part — do it now
        # Warm the cross-encoder reranker too (first predict is slow on CPU,
        # and on a fresh install this also downloads the ~80 MB model once).
        ce = _get_cross_encoder()
        if ce is not None:
            try:
                ce.predict([["warmup query", "warmup passage"]])
            except Exception:
                pass
        dt = (_time.perf_counter() - t0) * 1000.0
        print(f"[memory] RAG prewarmed in {dt:.0f} ms "
              f"(embeddings + reranker + collection ready, {col.count()} chunks).")
    except Exception as exc:                                            # noqa: BLE001
        print(f"[memory] prewarm failed (non-fatal): {exc}")


def embed_query(text: str):
    """
    Return the embedding vector (list[float]) for a single string using the
    shared all-MiniLM-L6-v2 model, or None if the model is unavailable. Reuses
    the prewarmed singleton, so this is ~ms once warm. Used by the semantic
    answer cache.
    """
    ef = _get_ef()
    if ef is None:
        return None
    try:
        out = ef([text])
        if out is None or len(out) == 0:
            return None
        return list(out[0])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Cross-encoder reranker
# ---------------------------------------------------------------------------
# The bi-encoder (all-MiniLM) ranks fast but coarsely — it embeds the query and
# each chunk separately. A cross-encoder reads (query, chunk) TOGETHER, which is
# much more accurate. We fetch a wide candidate set with the bi-encoder, then
# rerank down to the top-N with the cross-encoder. Optional + graceful: if the
# model can't load (offline first-run, missing dep), we keep the vector order.
_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_CE = None
_CE_tried = False


def _get_cross_encoder():
    global _CE, _CE_tried
    if _CE_tried:
        return _CE
    _CE_tried = True
    try:
        from sentence_transformers import CrossEncoder
        _CE = CrossEncoder(_RERANK_MODEL)
        print("[memory] Reranker loaded (cross-encoder/ms-marco-MiniLM-L-6-v2, CPU).")
    except Exception as exc:                                            # noqa: BLE001
        print(f"[memory] Reranker unavailable ({exc}); using vector order.")
        _CE = None
    return _CE


def _rerank(query: str, docs: list, metas: list, top_n: int):
    """Re-order (docs, metas) by cross-encoder relevance; return the top_n.
    Falls back to the original (vector) order if the reranker isn't available."""
    ce = _get_cross_encoder()
    if ce is None or len(docs) <= 1:
        return docs[:top_n], metas[:top_n]
    try:
        scores = ce.predict([[query, d] for d in docs])
        order = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)[:top_n]
        return [docs[i] for i in order], [metas[i] for i in order]
    except Exception as exc:                                            # noqa: BLE001
        print(f"[memory] rerank failed ({exc}); vector order.")
        return docs[:top_n], metas[:top_n]


def _chunk_text(text: str) -> list[str]:
    """Sliding-window text chunker with overlap."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end   = min(start + CHUNK_SIZE, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


def _chunk_id(path: Path, idx: int) -> str:
    """Stable deterministic ID for a chunk: sha1(absolute_path)[:12] + index."""
    digest = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:12]
    return f"{digest}_{idx}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def index_obsidian_vault(vault_path: str = "") -> str:
    """
    Recursively read all .md and .txt files under vault_path, split them
    into overlapping chunks, and upsert them into the persistent ChromaDB
    'obsidian_vault' collection.

    Returns a human-readable status string suitable for display in the
    Albedo chat log.
    """
    if not vault_path:
        vault_path = _default_vault()
    if not vault_path:
        return "[memory] OBSIDIAN_VAULT_PATH is not set. Run the onboarding wizard or set it in .env."
    root = Path(vault_path)
    if not root.exists():
        return f"[memory] Vault path not found: {vault_path}"

    files = sorted(root.rglob("*.md")) + sorted(root.rglob("*.txt"))
    if not files:
        return f"[memory] No .md or .txt files found under {vault_path}"

    docs:   list[str]  = []
    ids:    list[str]  = []
    metas:  list[dict] = []
    skipped = 0

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            skipped += 1
            continue
        if not text:
            continue
        for idx, chunk in enumerate(_chunk_text(text)):
            docs.append(chunk)
            ids.append(_chunk_id(path, idx))
            metas.append({"source": str(path), "chunk": idx})

    if not docs:
        return "[memory] Vault files found but all were empty."

    collection = _get_collection()

    # Upsert in batches of 100 to stay within ChromaDB limits.
    BATCH = 100
    for start in range(0, len(docs), BATCH):
        collection.upsert(
            documents=docs[start : start + BATCH],
            ids=ids[start : start + BATCH],
            metadatas=metas[start : start + BATCH],
        )

    skip_note = f" ({skipped} files skipped due to read errors)" if skipped else ""
    return (
        f"Successfully indexed {len(files) - skipped} files "
        f"({len(docs)} chunks) from the Obsidian vault{skip_note}."
    )


def search_memory(query: str, n_results: int = 3) -> list[str]:
    """
    Semantic search over the indexed Obsidian vault.

    Returns a list of the most relevant text chunks ordered by relevance.
    Returns an empty list on any error (missing index, embedding failure, etc.)
    so callers never have to handle exceptions.

    Auto-indexes the vault on first call if the collection is empty, so RAG
    works out of the box without requiring a manual REBUILD click.
    """
    try:
        collection = _get_collection()
        if collection.count() == 0:
            vault = _default_vault()
            if vault:
                print("[memory] Collection empty — auto-indexing vault on first search...")
                result = index_obsidian_vault(vault)
                print(f"[memory] {result}")
                # Re-fetch collection after indexing
                collection = _get_collection()
            if collection.count() == 0:
                return []
        # Fetch a WIDE candidate set with the fast bi-encoder, then rerank down
        # to the best n_results with the cross-encoder for precise ordering.
        fetch_k = min(max(n_results * 4, 12), collection.count())
        results = collection.query(
            query_texts=[query],
            n_results=fetch_k,
            include=["documents", "metadatas"],
        )
        cand_docs  = results.get("documents", [[]])[0] or []
        cand_metas = results.get("metadatas", [[]])[0] or []
        chunks, metas = _rerank(query, cand_docs, cand_metas, n_results)
        # Emit a rag.hit event so the Brain visualization can light up the
        # matched notes ("synapse firing"). Best-effort — bus is optional.
        try:
            notes = []
            seen = set()
            for m in metas:
                if not isinstance(m, dict):
                    continue
                p = str(m.get("path") or m.get("source") or "")
                t = str(m.get("title") or m.get("filename") or
                        (p.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if p else ""))
                key = p or t
                if key and key not in seen:
                    seen.add(key)
                    notes.append({"title": t, "path": p})
            if notes:
                from albedo import event_bus
                event_bus.publish("rag.hit", query=query, notes=notes)
        except Exception:
            pass
        return [c for c in chunks if c]
    except Exception as exc:
        print(f"[memory] Search error: {exc}")
        return []
