import logging
import os
import threading
import time

from .. import db
from ..config import settings
from .client import get_client
logger = logging.getLogger(__name__)

# Re-entrant: sync_capture calls forget_capture internally. Serializes
# overlapping background ingests for the same capture (create-task sync vs
# edit-task sync raced: stale docs were never deleted and the DB pointed at
# dead ids).
_SYNC_LOCK = threading.RLock()

_MAX_DELETE_WAIT = 90


def _memory_text(row) -> str:
    parts = [row["note"] or "", row["original_filename"] or "", row["content"] or ""]
    return "\n".join(p for p in parts if p).strip()


def _doc_ids(row) -> list[str]:
    raw = row["memory_doc_ids"] or ""
    return [d for d in raw.split(",") if d]


def _delete_with_retry(client, doc_id: str) -> bool:
    """supermemory rejects DELETE while a doc is still processing (409).

    Docs from a just-completed sync are usually mid-ingest, so poll status
    until the doc settles, then delete. Best-effort: give up quietly.
    """
    waited = 0
    while waited < _MAX_DELETE_WAIT:
        status = client.document_status(doc_id)
        if status in (None, "done", "failed"):
            return client.delete_document(doc_id)
        time.sleep(2)
        waited += 2
    return False


def _sweep_custom_id_docs(client, capture_id: int) -> list[str]:
    """Delete every doc whose customId starts with nm-{capture_id}- and return
    the ids removed.

    Self-healing fallback for deletion: the stored memory_doc_ids column can
    be empty (sync crashed before writing it back) and _delete_with_retry can
    time out on slow ingests — both leave orphans that retrieval still ranks.
    The customIds are deterministic, so a store scan finds everything this
    capture owns regardless of what the column says."""
    try:
        listing = client.list_documents()
    except Exception:
        return []
    prefix = f"nm-{capture_id}-"
    removed: list[str] = []
    for doc in listing:
        custom_id = (doc.get("customId") or "")
        if not custom_id.startswith(prefix):
            continue
        if client.delete_document(doc["id"]):
            removed.append(doc["id"])
    return removed


def forget_capture(capture_id: int) -> None:
    """Delete all knowledge-store docs owned by a capture (best-effort)."""
    if not settings.memory_enabled:
        return
    with _SYNC_LOCK:
        try:
            if settings.knowledge_backend == "chromadb":
                from ..retrieval.vector_store import delete_by_capture
                delete_by_capture(capture_id)
                return

            with db.get_conn() as conn:
                row = conn.execute(
                    "SELECT memory_doc_ids FROM captures WHERE id = ?", (capture_id,)
                ).fetchone()
                ids = _doc_ids(row) if row else []
                if ids:
                    conn.execute("UPDATE captures SET memory_doc_ids = NULL WHERE id = ?", (capture_id,))
            client = get_client()
            for doc_id in ids:
                _delete_with_retry(client, doc_id)
            _sweep_custom_id_docs(client, capture_id)
        except Exception as exc:
            logger.warning("memory forget failed for capture %s: %s", capture_id, exc)


def _sync_chromadb(capture_id: int, row) -> None:
    """ChromaDB sync path: chunk → embed → upsert."""
    from ..ingestion.chunker import chunk as do_chunk
    from ..embeddings.provider import embed
    from ..retrieval.vector_store import upsert, count

    raw = _memory_text(row)
    if not raw:
        return
    chunks = [c["text"] for c in do_chunk(raw)]
    if not chunks:
        return
    vectors = embed(chunks)
    stored = upsert(capture_id, chunks, vectors)
    logger.info("chromadb sync: capture %d → %d chunks (store total: %d)", capture_id, stored, count())


def _custom_id(capture_id: int, slot: str) -> str:
    return f"nm-{capture_id}-{slot}"


# The lite server's memory agent feeds the model a bounded, beginning-biased
# window of document text (~13.5K-token prompt budget). A novel-length
# document (944K chars) therefore yielded only 3 opening-scene facts. Above
# this threshold, sync splits the text into paragraph-boundary segments and
# syncs each as its own raw doc — every segment gets a FULL agent run, so
# graph coverage scales with book size. All segments share metadata
# (capture_id) so scoped reads/hybrid hits treat them as one document.
_SEGMENT_SYNC_MIN_CHARS = int(os.getenv("SYNC_SEGMENT_MIN_CHARS", "100000"))
_SEGMENT_CHARS = int(os.getenv("SYNC_SEGMENT_CHARS", "80000"))


def _segment_content(text: str) -> list[str]:
    if len(text) <= _SEGMENT_SYNC_MIN_CHARS:
        return [text]
    parts: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + _SEGMENT_CHARS, n)
        if end < n:
            cut = text.rfind("\n\n", start + _SEGMENT_CHARS // 2, end)
            if cut > start:
                end = cut + 2
        parts.append(text[start:end])
        start = end
    return parts


def sync_capture(capture_id: int) -> None:
    """Push a capture into supermemory as one raw-content doc.

    Design rules (handoff §3, carried from v1):
      - memory holds only the latest version per document group — syncing a
        capture forgets its siblings first (is_latest semantics supermemory
        doesn't know)
      - every doc keeps capture_id / sensitivity_tier / type metadata so
        retrieval can cite sources (tiers are labels only — nothing is gated)
      - docs carry deterministic customIds (nm-{capture_id}-raw) so edits
        upsert in place instead of racing deletes against the ingester
        (DELETE during processing returns 409); documents above
        SYNC_SEGMENT_MIN_CHARS are split into nm-{id}-raw-0..N segments so
        each receives a full memory-agent pass (the agent reads only a bounded
        window per call — one run on a whole novel captured ~3 opening facts)
      - understanding is the server's job: its memory agent (Gemini or local,
        see scripts/run-supermemory.sh) extracts graph memories — no local
        fact extraction anymore
      - all best-effort: supermemory down = capture still indexes
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

            client = get_client()
            tag = settings.memory_container_tag
            meta = {
                "capture_id": str(capture_id),
                "sensitivity_tier": row["sensitivity_tier"],
                "type": row["type"],
                "kind": "raw",
            }

            raw = _memory_text(row)
            doc_ids: list[str] = []
            if settings.knowledge_backend == "chromadb":
                _sync_chromadb(capture_id, row)
                with db.get_conn() as conn:
                    conn.execute(
                        "UPDATE captures SET memory_doc_ids = ? WHERE id = ?",
                        ("chromadb-synced", capture_id),
                    )
                return

            if raw:
                base_custom = _custom_id(capture_id, "raw")
                segments = _segment_content(raw)
                slots = [base_custom] if len(segments) == 1 else [
                    f"{base_custom}-{i}" for i in range(len(segments))
                ]
                for custom_id, segment in zip(slots, segments):
                    doc_id = client.add_document(segment, tag, meta, custom_id=custom_id)
                    if doc_id:
                        doc_ids.append(doc_id)

            if doc_ids:
                with db.get_conn() as conn:
                    conn.execute(
                        "UPDATE captures SET memory_doc_ids = ? WHERE id = ?",
                        (",".join(doc_ids), capture_id),
                    )
        except Exception as exc:
            logger.warning("memory sync failed for capture %s: %s", capture_id, exc)