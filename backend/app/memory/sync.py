import logging
import threading
import time

from .. import db
from ..config import settings
from .client import get_client
from .facts import facts_for_capture

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


def forget_capture(capture_id: int) -> None:
    """Delete all supermemory docs owned by a capture (best-effort).

    Called on capture delete, edit re-ingest, version demotion.
    """
    if not settings.memory_enabled:
        return
    with _SYNC_LOCK:
        try:
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
        except Exception as exc:
            logger.warning("memory forget failed for capture %s: %s", capture_id, exc)


def _custom_id(capture_id: int, slot: str) -> str:
    return f"nm-{capture_id}-{slot}"


def sync_capture(capture_id: int) -> None:
    """Push a capture into supermemory as one raw-content doc + fact docs.

    Design rules (handoff §3, carried from v1):
      - memory holds only the latest version per document group — syncing a
        capture forgets its siblings first (is_latest semantics supermemory
        doesn't know)
      - every doc keeps capture_id / sensitivity_tier / type metadata so
        retrieval can cite sources (tiers are labels only — nothing is gated)
      - docs carry deterministic customIds (nm-{capture_id}-{slot}) so edits
        upsert in place instead of racing deletes against the ingester
        (DELETE during processing returns 409)
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
            base_meta = {
                "capture_id": str(capture_id),
                "sensitivity_tier": row["sensitivity_tier"],
                "type": row["type"],
            }
            docs: list[str] = []

            raw = _memory_text(row)
            if raw:
                doc_id = client.add_document(
                    raw,
                    tag,
                    {**base_meta, "kind": "raw"},
                    custom_id=_custom_id(capture_id, "raw"),
                )
                if doc_id:
                    docs.append(doc_id)

            fact_kind = _fact_kind(row["type"], row["content"])
            for i, fact in enumerate(facts_for_capture(row["type"], row["content"])):
                doc_id = client.add_document(
                    fact,
                    tag,
                    {**base_meta, "kind": "fact", "fact_kind": fact_kind},
                    custom_id=_custom_id(capture_id, f"f{i}"),
                )
                if doc_id:
                    docs.append(doc_id)

            if docs:
                with db.get_conn() as conn:
                    conn.execute(
                        "UPDATE captures SET memory_doc_ids = ? WHERE id = ?",
                        (",".join(docs), capture_id),
                    )
        except Exception as exc:
            logger.warning("memory sync failed for capture %s: %s", capture_id, exc)


def _fact_kind(capture_type: str, content: str) -> str:
    if capture_type == "doc":
        if "TRANSCRIPT" in content.upper() or "GRADE" in content.upper():
            return "transcript"
        if "RESUME" in content.upper() or "EDUCATION" in content.upper():
            return "resume"
    return "note"