from __future__ import annotations

import os
from pathlib import Path

import chromadb
from albedo.config import (
    CHROMA_DB_PATH,
    COLLECTION_CHAOTIC_3D,
    COLLECTION_EXOTIC_OS,
    RAG_TOP_K,
)

# ---------------------------------------------------------------------------
# Embedding function — lazy-initialised so a corrupt model file does not
# freeze the process at import time (Errno 22 / OSError on .bin/.pkl files).
# If initialisation fails, _get_ef() returns None and all queries fall back
# to token-overlap keyword search automatically.
# ---------------------------------------------------------------------------

_ef = None          # SentenceTransformerEmbeddingFunction or None
_ef_tried = False   # True once we have attempted init (success or failure)


_HF_CACHE = Path.home() / ".cache" / "huggingface" / "hub"
_MODEL_CACHE_PREFIX = "models--sentence-transformers--all-MiniLM-L6-v2"


def _model_is_cached() -> bool:
    """True if the sentence-transformer model exists in the local HF cache."""
    try:
        return any(
            p.name.startswith(_MODEL_CACHE_PREFIX)
            for p in _HF_CACHE.iterdir()
        ) if _HF_CACHE.exists() else False
    except Exception:
        return False


def _get_ef():
    global _ef, _ef_tried
    if _ef_tried:
        return _ef
    _ef_tried = True
    try:
        from chromadb.utils import embedding_functions

        # If the model is already cached locally, force offline mode so the
        # loader never makes a network call that can fail on a hiccup.
        cached = _model_is_cached()
        _prev  = os.environ.get("HF_HUB_OFFLINE")
        if cached:
            os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            _ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2",
                device="cpu",
            )
        finally:
            if _prev is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = _prev

        print("[retriever] Embedding model loaded (all-MiniLM-L6-v2, CPU).")
    except Exception as exc:
        print(
            f"[retriever] WARNING: embedding model failed to load "
            f"({type(exc).__name__}: {exc}).\n"
            "[retriever] Using keyword search fallback. "
            "Restart with a stable connection to download the model once."
        )
        _ef = None
    return _ef


_client: chromadb.PersistentClient | None = None


def _get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    return _client


# ---------------------------------------------------------------------------
# Keyword fallback — token overlap ranking, no model required
# ---------------------------------------------------------------------------

def _keyword_fallback(col, query: str, n_results: int) -> list[dict]:
    """Simple token-overlap search used when the embedding model is unavailable."""
    try:
        all_docs = col.get(include=["documents", "metadatas"])
        tokens = set(query.lower().split())
        scored: list[tuple[int, str, dict]] = []
        for doc, meta in zip(all_docs["documents"], all_docs["metadatas"]):
            overlap = sum(1 for t in tokens if t in doc.lower())
            if overlap:
                scored.append((overlap, doc, meta or {}))
        scored.sort(reverse=True)
        return [
            {"text": doc, "source": meta.get("source", ""), "score": 0.0}
            for _, doc, meta in scored[:n_results]
        ]
    except Exception as exc:
        print(f"[retriever] Keyword fallback also failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Core query logic
# ---------------------------------------------------------------------------

def _query_collection(collection_name: str, query: str, top_k: int) -> list[dict]:
    client = _get_client()
    ef = _get_ef()

    try:
        col = client.get_collection(collection_name, embedding_function=ef)
    except Exception:
        return []

    count = col.count()
    if count == 0:
        return []

    n_results = min(count, max(top_k, 3))

    # No embedding model available — skip straight to keyword fallback
    if ef is None:
        return _keyword_fallback(col, query, n_results)

    # Semantic search via embedding model
    try:
        results = col.query(query_texts=[query], n_results=n_results)
        chunks = []
        for doc, meta, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            chunks.append({"text": doc, "source": meta.get("source", ""), "score": distance})
        return chunks
    except Exception as exc:
        print(
            f"[retriever] Embedding query failed "
            f"({type(exc).__name__}: {exc}); using keyword fallback."
        )
        return _keyword_fallback(col, query, n_results)


def query_chaotic_3d(query: str, top_k: int = RAG_TOP_K) -> list[dict]:
    return _query_collection(COLLECTION_CHAOTIC_3D, query, top_k)


def query_exotic_os(query: str, top_k: int = RAG_TOP_K) -> list[dict]:
    return _query_collection(COLLECTION_EXOTIC_OS, query, top_k)


def query_all(query: str, top_k: int = RAG_TOP_K) -> dict[str, list[dict]]:
    return {
        "chaotic_3d": query_chaotic_3d(query, top_k),
        "exotic_os":  query_exotic_os(query, top_k),
    }
