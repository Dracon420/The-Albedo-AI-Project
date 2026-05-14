"""
ChromaDB indexer — memory-optimised for 16 GB RAM.

Key changes vs naive approach:
  - Existing IDs are fetched in pages (INDEXER_ID_PAGE_SIZE), not all at once.
  - Documents are added in batches (INDEXER_BATCH_SIZE) to cap peak RAM.
  - Files larger than INDEXER_MAX_FILE_BYTES are read in 1 MB streaming blocks.
  - gc.collect() is called between collections to reclaim embedding-model buffers.
"""

import gc
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path
from albedo.config import (
    CHROMA_DB_PATH,
    CHAOTIC_3D_PATH,
    EXOTIC_OS_PATH,
    CHAOTIC_3D_EXTENSIONS,
    EXOTIC_OS_EXTENSIONS,
    COLLECTION_CHAOTIC_3D,
    COLLECTION_EXOTIC_OS,
    INDEXER_BATCH_SIZE,
    INDEXER_ID_PAGE_SIZE,
    INDEXER_MAX_FILE_BYTES,
)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

_ef = embedding_functions.DefaultEmbeddingFunction()


def _get_client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=str(CHROMA_DB_PATH))


def _chunk_text(text: str) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if c.strip()]


def _read_file_safe(file: Path) -> str | None:
    """Read a file in streaming 1 MB blocks to cap RAM use on large files."""
    try:
        size = file.stat().st_size
        if size == 0:
            return None
        if size <= INDEXER_MAX_FILE_BYTES:
            return file.read_text(encoding="utf-8", errors="ignore")
        # Stream large files block by block
        BLOCK = 1024 * 1024
        parts: list[str] = []
        with file.open(encoding="utf-8", errors="ignore") as fh:
            while True:
                block = fh.read(BLOCK)
                if not block:
                    break
                parts.append(block)
                if sum(len(p) for p in parts) >= INDEXER_MAX_FILE_BYTES:
                    break
        return "".join(parts)
    except Exception:
        return None


def _fetch_existing_ids(collection: chromadb.Collection) -> set[str]:
    """Page through all stored IDs without loading document content."""
    existing: set[str] = set()
    offset = 0
    while True:
        page = collection.get(
            limit=INDEXER_ID_PAGE_SIZE,
            offset=offset,
            include=[],          # IDs only — no embeddings or documents in RAM
        )
        ids = page.get("ids", [])
        if not ids:
            break
        existing.update(ids)
        offset += len(ids)
        if len(ids) < INDEXER_ID_PAGE_SIZE:
            break
    return existing


def _flush_batch(
    collection: chromadb.Collection,
    ids: list[str],
    docs: list[str],
    metas: list[dict],
) -> int:
    if not ids:
        return 0
    collection.add(ids=ids, documents=docs, metadatas=metas)
    count = len(ids)
    ids.clear()
    docs.clear()
    metas.clear()
    return count


def _index_directory(
    collection: chromadb.Collection,
    directory: Path,
    extensions: set[str],
) -> int:
    print(f"  [indexer] Fetching existing IDs from '{collection.name}'...")
    existing_ids = _fetch_existing_ids(collection)
    print(f"  [indexer] {len(existing_ids)} chunks already indexed.")

    total_new = 0
    batch_ids: list[str] = []
    batch_docs: list[str] = []
    batch_metas: list[dict] = []

    for file in directory.rglob("*"):
        if file.suffix.lower() not in extensions or not file.is_file():
            continue

        text = _read_file_safe(file)
        if not text or not text.strip():
            continue

        chunks = _chunk_text(text)
        del text  # release file content before embedding

        for i, chunk in enumerate(chunks):
            doc_id = f"{file.as_posix()}::{i}"
            if doc_id in existing_ids:
                continue
            batch_ids.append(doc_id)
            batch_docs.append(chunk)
            batch_metas.append({"source": str(file), "chunk": i})

            if len(batch_ids) >= INDEXER_BATCH_SIZE:
                total_new += _flush_batch(collection, batch_ids, batch_docs, batch_metas)
                print(f"  [indexer] {total_new} new chunks indexed...", end="\r")

        del chunks

    # Flush remaining partial batch
    total_new += _flush_batch(collection, batch_ids, batch_docs, batch_metas)
    print(f"  [indexer] Done — {total_new} new chunks added to '{collection.name}'.")
    return total_new


def index_chaotic_3d() -> int:
    if not CHAOTIC_3D_PATH or not CHAOTIC_3D_PATH.exists():
        raise FileNotFoundError(f"CHAOTIC_3D_PATH not found: {CHAOTIC_3D_PATH}")
    client = _get_client()
    col = client.get_or_create_collection(COLLECTION_CHAOTIC_3D, embedding_function=_ef)
    result = _index_directory(col, CHAOTIC_3D_PATH, CHAOTIC_3D_EXTENSIONS)
    gc.collect()
    return result


def index_exotic_os() -> int:
    if not EXOTIC_OS_PATH or not EXOTIC_OS_PATH.exists():
        raise FileNotFoundError(f"EXOTIC_OS_PATH not found: {EXOTIC_OS_PATH}")
    client = _get_client()
    col = client.get_or_create_collection(COLLECTION_EXOTIC_OS, embedding_function=_ef)
    result = _index_directory(col, EXOTIC_OS_PATH, EXOTIC_OS_EXTENSIONS)
    gc.collect()
    return result


def index_all() -> dict[str, int]:
    results: dict[str, int] = {}
    for label, fn in [("chaotic_3d", index_chaotic_3d), ("exotic_os", index_exotic_os)]:
        try:
            results[label] = fn()
        except FileNotFoundError as e:
            print(f"  [indexer] Skipping {label}: {e}")
            results[label] = 0
        gc.collect()
    return results
