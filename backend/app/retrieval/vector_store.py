"""ChromaDB-backed vector store — the v4 knowledge layer.

Replaces supermemory-server: we own upsert, search, and deletion.
Persists to disk (NOTE_MASTER_DATA_DIR/chromadb/). Each chunk carries
metadata {capture_id, chunk_index} so retrieval can cite sources and
deletion can scope by capture.
"""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_client = None
_collection = None

_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", str(Path(__file__).resolve().parents[2] / "data" / "chromadb"))
_COLLECTION_NAME = "note_master"


def _get_collection():
    global _client, _collection
    if _collection is None:
        import chromadb

        Path(_PERSIST_DIR).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=_PERSIST_DIR)
        # embedding_function=None → we pass pre-computed embeddings
        _collection = _client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def upsert(
    capture_id: int,
    chunks: list[str],
    embeddings: list[list[float]],
) -> int:
    """Insert or update chunks for a capture. Returns count stored."""
    col = _get_collection()
    ids = [f"nm-{capture_id}-chunk-{i}" for i in range(len(chunks))]
    metadatas = [{"capture_id": str(capture_id), "chunk_index": i} for i in range(len(chunks))]
    col.upsert(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas)
    logger.info("vector_store: upserted %d chunks for capture %d", len(chunks), capture_id)
    return len(chunks)


def search(query_embedding: list[float], k: int = 10) -> list[dict]:
    """Nearest-neighbour search. Returns hits sorted by similarity descending:
    [{capture_id: int, snippet: str, distance: float}, ...]."""
    col = _get_collection()
    results = col.query(query_embeddings=[query_embedding], n_results=min(k, col.count()))
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    out = []
    for doc, meta, dist in zip(docs, metas, dists):
        out.append({
            "capture_id": int(meta["capture_id"]),
            "snippet": doc,
            "similarity": round(1.0 - dist, 4),  # cosine distance → similarity
        })
    return out


def delete_by_capture(capture_id: int) -> int:
    """Delete all chunks belonging to a capture. Returns count deleted."""
    col = _get_collection()
    try:
        pre_count = col.count()
        col.delete(where={"capture_id": str(capture_id)})
        deleted = pre_count - col.count()
        if deleted:
            logger.info("vector_store: deleted %d chunks for capture %d", deleted, capture_id)
        return deleted
    except Exception as exc:
        logger.warning("vector_store delete failed for capture %d: %s", capture_id, exc)
        return 0


def reset() -> None:
    """Delete the entire collection (empty-store reset)."""
    global _collection
    client = _get_collection()
    col = _client.get_or_create_collection(name=_COLLECTION_NAME)
    _client.delete_collection(_COLLECTION_NAME)
    _collection = None


def count() -> int:
    """Total chunks in the store."""
    return _get_collection().count()
