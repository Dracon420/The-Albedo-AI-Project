import chromadb
from chromadb.utils import embedding_functions
from albedo.config import (
    CHROMA_DB_PATH,
    COLLECTION_CHAOTIC_3D,
    COLLECTION_EXOTIC_OS,
    RAG_TOP_K,
)

_ef = embedding_functions.DefaultEmbeddingFunction()
_client: chromadb.PersistentClient | None = None


def _get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    return _client


def _query_collection(collection_name: str, query: str, top_k: int) -> list[dict]:
    client = _get_client()
    try:
        col = client.get_collection(collection_name, embedding_function=_ef)
    except Exception:
        return []

    results = col.query(query_texts=[query], n_results=min(top_k, col.count()))
    chunks = []
    for doc, meta, distance in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({"text": doc, "source": meta.get("source", ""), "score": distance})
    return chunks


def query_chaotic_3d(query: str, top_k: int = RAG_TOP_K) -> list[dict]:
    return _query_collection(COLLECTION_CHAOTIC_3D, query, top_k)


def query_exotic_os(query: str, top_k: int = RAG_TOP_K) -> list[dict]:
    return _query_collection(COLLECTION_EXOTIC_OS, query, top_k)


def query_all(query: str, top_k: int = RAG_TOP_K) -> dict[str, list[dict]]:
    return {
        "chaotic_3d": query_chaotic_3d(query, top_k),
        "exotic_os": query_exotic_os(query, top_k),
    }
