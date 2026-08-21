import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from .. import db, storage
from ..memory.sync import sync_capture
# SENSITIVE-FACTS (OPT2): dormant — uncomment to restore the 3b identity-fact
# extraction at ingest (schedule + tasks.py + routes/chat.py must be revived
# together). Identity is now handled entirely by supermemory retrieval.
# from . import sensitive
from .asr import transcribe
from .classify import classify
from .ocr import extract_doc

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
# Big or page-heavy documents are extracted in a disposable OS process: the
# native stack (Docling/pymupdf/OCR engines) can segfault or wedge on
# pathological files — in-process that takes down the whole serving app and
# strands the capture in 'processing' forever (the 959-page PDF incident).
_EXTRACT_SUBPROCESS_MIN_PAGES = int(os.getenv("EXTRACT_SUBPROCESS_MIN_PAGES", "60"))
_EXTRACT_SUBPROCESS_MIN_BYTES = int(os.getenv("EXTRACT_SUBPROCESS_MIN_BYTES", str(25 * 1024 * 1024)))
_EXTRACT_TIMEOUT_SECONDS = int(os.getenv("EXTRACT_TIMEOUT_SECONDS", "7200"))

_WORKER_SRC = (
    "import json, sys\n"
    "from pathlib import Path\n"
    "from app.ingestion.ocr import extract_doc\n"
    "text = extract_doc(Path(sys.argv[1]))\n"
    "sys.stdout.write('<<<NM_RESULT>>>' + json.dumps({'text': text}))\n"
)


def _needs_subprocess(path: Path) -> bool:
    try:
        if path.stat().st_size > _EXTRACT_SUBPROCESS_MIN_BYTES:
            return True
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            return len(PdfReader(path).pages) > _EXTRACT_SUBPROCESS_MIN_PAGES
    except Exception:
        return True  # unreadable/odd file — isolate it
    return False


def _extract_in_subprocess(path: Path) -> str:
    """Run extract_doc in `python -c` with cwd=backend root so `app` imports.
    Hard timeout kills hung extractions; nonzero exit (segfault included)
    surfaces as a clean RuntimeError instead of a dead server."""
    logger.info("extracting %s in subprocess (timeout %ss)", path.name, _EXTRACT_TIMEOUT_SECONDS)
    result = subprocess.run(
        [sys.executable, "-c", _WORKER_SRC, str(path)],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        timeout=_EXTRACT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        tail = (result.stderr or "")[-400:].strip()
        raise RuntimeError(f"extraction worker crashed (exit {result.returncode}): {tail}")
    marker = "<<<NM_RESULT>>>"
    idx = result.stdout.rfind(marker)
    if idx == -1:
        raise RuntimeError("extraction worker produced no result payload")
    return json.loads(result.stdout[idx + len(marker):])["text"]


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
    # Phase 1 — read what we need, CLOSE the connection: a hours-long
    # extraction must never hold a SQLite handle open (it wedged /captures).
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
        if row is None:
            return
        doc_ref = row["raw_content_ref"] if row["type"] == "doc" else None
        voice_ref = row["raw_content_ref"] if row["type"] == "voice" else None

    # Phase 2 — extract with NO open connection (possibly in a subprocess).
    content = row["content"] or ""
    if doc_ref:
        src = Path(storage.resolve_path(doc_ref))
        content = _extract_in_subprocess(src) if _needs_subprocess(src) else extract_doc(src)
    elif voice_ref:
        content = transcribe(Path(storage.resolve_path(voice_ref)))
    if not content:
        raise ValueError("no content extracted (empty or failed OCR/ASR)")
    tier = classify(content, row["original_filename"], row["note"])
    # SENSITIVE-FACTS (OPT2): dormant — identity facts were extracted here
    # once per high-tier doc (never synced, deterministic answers). Now
    # supermemory retrieval handles identity; the column is left NULL.
    # facts = sensitive.extract_sensitive_facts(content) if tier == "high" else {}

    # Phase 3 — write results.
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE captures SET content = ?, status = 'indexed', error = NULL, sensitivity_tier = ?, sensitive_facts = NULL WHERE id = ?",
            (content, tier, capture_id),
        )
    sync_capture(capture_id)