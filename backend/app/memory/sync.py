import logging
import threading

from .. import db
from ..config import settings
logger = logging.getLogger(__name__)

# Re-entrant: sync_capture calls forget_capture internally. Serializes
# overlapping background ingests for the same capture (create-task sync vs
# edit-task sync raced: stale docs were never deleted and the DB pointed at
# dead ids).
_SYNC_LOCK = threading.RLock()


def _memory_text(row) -> str:
    parts = [row["note"] or "", row["original_filename"] or "", row["content"] or ""]
    return "\n".join(p for p in parts if p).strip()


def forget_capture(capture_id: int) -> None:
    """Delete all vector-store chunks owned by a capture (best-effort)."""
    if not settings.memory_enabled:
        return
    with _SYNC_LOCK:
        try:
            from ..retrieval.vector_store import delete_by_capture
            delete_by_capture(capture_id)
        except Exception as exc:
            logger.warning("memory forget failed for capture %s: %s", capture_id, exc)


def _sync_chromadb(capture_id: int, row) -> None:
    """ChromaDB sync path: chunk → filter → embed → upsert."""
    from ..ingestion.chunker import chunk as do_chunk
    from ..embeddings.provider import embed
    from ..retrieval.vector_store import upsert, count

    raw = _memory_text(row)
    if not raw:
        return
    all_chunks = [c["text"] for c in do_chunk(raw)]
    # Filter whitespace-only/trivially-small chunks — they pollute vector
    # search by scoring mid-range similarity against EVERY query despite
    # carrying zero information. Also drop majority-whitespace formatting
    # dumps (script/table fragments) at the source so they never compete for
    # candidate-pool slots at query time.
    def _keep(c: str) -> bool:
        if len(c.strip()) < 20:
            return False
        if sum(1 for ch in c if ch.isspace()) / len(c) > 0.6:
            return False
        return True

    chunks = [c for c in all_chunks if _keep(c)]
    if not chunks:
        logger.warning("chromadb sync: capture %d produced 0 clean chunks (of %d)", capture_id, len(all_chunks))
        return
    vectors = embed(chunks)
    stored = upsert(capture_id, chunks, vectors)
    logger.info("chromadb sync: capture %d → %d/%d chunks (store total: %d)", capture_id, stored, len(all_chunks), count())


def sync_capture(capture_id: int) -> None:
    """Index a capture's text into the local ChromaDB vector store.

    Design rules:
      - the store holds only the latest version per document group — syncing
        a capture forgets its siblings first
      - every chunk carries capture_id metadata so retrieval can cite sources
      - understanding is the embedder's job: nomic-embed-text (local, 768-dim)
      - all best-effort: ChromaDB/embedder down = capture still indexes
    """
    if not settings.memory_enabled:
        return
    with _SYNC_LOCK:
        try:
            with db.get_conn() as conn:
                row = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
                if row is None:
                    return
                sibling_ids = [
                    r["id"]
                    for r in conn.execute(
                        "SELECT id FROM captures WHERE document_group_id = ? AND id != ? AND is_latest = 0",
                        (row["document_group_id"], capture_id),
                    ).fetchall()
                ]
            for sibling in sibling_ids:
                forget_capture(sibling)
            forget_capture(capture_id)
            _sync_chromadb(capture_id, row)
        except Exception as exc:
            logger.warning("memory sync failed for capture %s: %s", capture_id, exc)