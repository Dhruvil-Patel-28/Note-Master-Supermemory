from pathlib import Path
import json
import logging

from .. import db, storage
from ..memory.sync import sync_capture
from . import sensitive
from .asr import transcribe
from .classify import classify
from .ocr import extract_doc

logger = logging.getLogger(__name__)


def create_capture(
    type_: str,
    content: str = "",
    raw_content_ref: str = None,
    original_filename: str = None,
    note: str = None,
    document_group_id: int = None,
    user_id: int = None,
) -> int:
    with db.get_conn() as conn:
        if document_group_id is None:
            cur = conn.execute(
                "INSERT INTO captures (type, content, raw_content_ref, original_filename, note, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                (type_, content, raw_content_ref, original_filename, note, user_id),
            )
            capture_id = cur.lastrowid
            conn.execute(
                "UPDATE captures SET document_group_id = ? WHERE id = ?",
                (capture_id, capture_id),
            )
            return capture_id
        conn.execute(
            "UPDATE captures SET is_latest = 0 WHERE document_group_id = ?",
            (document_group_id,),
        )
        version = conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) FROM captures WHERE document_group_id = ?",
            (document_group_id,),
        ).fetchone()[0] + 1
        cur = conn.execute(
            """INSERT INTO captures
               (type, content, raw_content_ref, original_filename, note, status, document_group_id, version_number, is_latest, user_id)
               VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, 1, ?)""",
            (type_, content, raw_content_ref, original_filename, note, document_group_id, version, user_id),
        )
        return cur.lastrowid


def run_pipeline(capture_id: int) -> None:
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
        if row is None:
            return
        conn.execute("UPDATE captures SET status = 'processing' WHERE id = ?", (capture_id,))
    try:
        _extract_and_index(capture_id)
    except Exception as exc:
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE captures SET status = 'failed', error = ? WHERE id = ?",
                (str(exc), capture_id),
            )
        raise


def _extract_and_index(capture_id: int) -> None:
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
        content = row["content"]
        if row["type"] == "doc" and row["raw_content_ref"]:
            content = extract_doc(Path(storage.resolve_path(row["raw_content_ref"])))
        elif row["type"] == "voice" and row["raw_content_ref"]:
            content = transcribe(Path(storage.resolve_path(row["raw_content_ref"])))
        if not content:
            raise ValueError("no content extracted (empty or failed OCR/ASR)")
        tier = classify(content, row["original_filename"], row["note"])
        # High-tier docs get their identity facts extracted once, stored
        # locally only (never synced) so "what is my address" can be answered
        # deterministically behind the PIN gate even when OCR mangled labels.
        facts = sensitive.extract_sensitive_facts(content) if tier == "high" else {}
        conn.execute(
            "UPDATE captures SET content = ?, status = 'indexed', error = NULL, sensitivity_tier = ?, sensitive_facts = ? WHERE id = ?",
            (content, tier, json.dumps(facts), capture_id),
        )
    sync_capture(capture_id)