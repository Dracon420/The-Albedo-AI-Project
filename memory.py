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

DEFAULT_VAULT = r"C:\Users\demon\Desktop\Albedo Project Brain"
DB_PATH       = str(Path(__file__).parent / "albedo_memory_db")
COLLECTION    = "obsidian_vault"
CHUNK_SIZE    = 1000
CHUNK_OVERLAP = 200

# Singleton embedding function — loaded once, reused across calls.
_EF = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=DB_PATH)
    return client.get_or_create_collection(
        name=COLLECTION,
        embedding_function=_EF,
    )


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

def index_obsidian_vault(vault_path: str = DEFAULT_VAULT) -> str:
    """
    Recursively read all .md and .txt files under vault_path, split them
    into overlapping chunks, and upsert them into the persistent ChromaDB
    'obsidian_vault' collection.

    Returns a human-readable status string suitable for display in the
    Albedo chat log.
    """
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
    """
    try:
        collection = _get_collection()
        if collection.count() == 0:
            return []
        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count()),
            include=["documents", "metadatas"],
        )
        chunks = results.get("documents", [[]])[0]
        return [c for c in chunks if c]
    except Exception as exc:
        print(f"[memory] Search error: {exc}")
        return []
