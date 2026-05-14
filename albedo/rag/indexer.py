from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions
from albedo.config import (
    CHROMA_DB_PATH,
    CHAOTIC_3D_PATH,
    EXOTIC_OS_PATH,
    CHAOTIC_3D_EXTENSIONS,
    EXOTIC_OS_EXTENSIONS,
    COLLECTION_CHAOTIC_3D,
    COLLECTION_EXOTIC_OS,
)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

_ef = embedding_functions.DefaultEmbeddingFunction()


def _get_client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=str(CHROMA_DB_PATH))


def _chunk_text(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if c.strip()]


def _index_directory(
    collection: chromadb.Collection,
    directory: Path,
    extensions: set[str],
) -> int:
    indexed = 0
    existing_ids: set[str] = set(collection.get()["ids"])

    for file in directory.rglob("*"):
        if file.suffix.lower() not in extensions or not file.is_file():
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not text.strip():
            continue

        chunks = _chunk_text(text)
        for i, chunk in enumerate(chunks):
            doc_id = f"{file.as_posix()}::{i}"
            if doc_id in existing_ids:
                continue
            collection.add(
                ids=[doc_id],
                documents=[chunk],
                metadatas=[{"source": str(file), "chunk": i}],
            )
            indexed += 1

    return indexed


def index_chaotic_3d() -> int:
    if not CHAOTIC_3D_PATH or not CHAOTIC_3D_PATH.exists():
        raise FileNotFoundError(f"CHAOTIC_3D_PATH not found: {CHAOTIC_3D_PATH}")
    client = _get_client()
    col = client.get_or_create_collection(COLLECTION_CHAOTIC_3D, embedding_function=_ef)
    return _index_directory(col, CHAOTIC_3D_PATH, CHAOTIC_3D_EXTENSIONS)


def index_exotic_os() -> int:
    if not EXOTIC_OS_PATH or not EXOTIC_OS_PATH.exists():
        raise FileNotFoundError(f"EXOTIC_OS_PATH not found: {EXOTIC_OS_PATH}")
    client = _get_client()
    col = client.get_or_create_collection(COLLECTION_EXOTIC_OS, embedding_function=_ef)
    return _index_directory(col, EXOTIC_OS_PATH, EXOTIC_OS_EXTENSIONS)


def index_all() -> dict[str, int]:
    results = {}
    for label, fn in [("chaotic_3d", index_chaotic_3d), ("exotic_os", index_exotic_os)]:
        try:
            results[label] = fn()
        except FileNotFoundError as e:
            print(f"[indexer] Skipping {label}: {e}")
            results[label] = 0
    return results
