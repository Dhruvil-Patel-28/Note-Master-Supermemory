from pathlib import Path
import logging

from .. import db, graph, storage
from .chunker import chunk_text
from .embeddings import embed_texts
from .ocr import extract_doc

logger = logging.getLogger(__name__)


def _write_chunks(conn, capture_id: int, content: str) -> None:
    conn.execute("DELETE FROM capture_chunks WHERE capture_id = ?", (capture_id,))
    chunks = chunk_text(content)
    if not chunks:
        return
    embeddings = embed_texts(chunks)
    for i, (text, embedding) in enumerate(zip(chunks, embeddings)):
        cur = conn.execute(
            "INSERT INTO capture_chunks (capture_id, chunk_index, text) VALUES (?, ?, ?)",
            (capture_id, i, text),
        )
        conn.execute(
            "INSERT INTO chunks_vec (rowid, embedding) VALUES (?, ?)",
            (cur.lastrowid, str(embedding)),
        )


def _write_graph(conn, capture_id: int, content: str) -> None:
    sibling_ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM captures WHERE document_group_id = (SELECT document_group_id FROM captures WHERE id = ?) AND id != ?",
            (capture_id, capture_id),
        ).fetchall()
    ]
    try:
        graph.write_capture(capture_id, content, sibling_ids)
    except Exception as exc:
        logger.warning("graph write failed for capture %s: %s", capture_id, exc)


def create_capture(
    type_: str,
    content: str = "",
    raw_content_ref: str = None,
    document_group_id: int = None,
    user_id: int = None,
) -> int:
    with db.get_conn() as conn:
        if document_group_id is None:
            cur = conn.execute(
                "INSERT INTO captures (type, content, raw_content_ref, user_id) VALUES (?, ?, ?, ?)",
                (type_, content, raw_content_ref, user_id),
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
               (type, content, raw_content_ref, status, document_group_id, version_number, is_latest, user_id)
               VALUES (?, ?, ?, 'queued', ?, ?, 1, ?)""",
            (type_, content, raw_content_ref, document_group_id, version, user_id),
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
        conn.execute(
            "UPDATE captures SET content = ?, status = 'indexed', error = NULL WHERE id = ?",
            (content, capture_id),
        )
        conn.execute("DELETE FROM captures_fts WHERE rowid = ?", (capture_id,))
        conn.execute(
            "INSERT INTO captures_fts (rowid, content) VALUES (?, ?)",
            (capture_id, content),
        )
        _write_chunks(conn, capture_id, content)
        _write_graph(conn, capture_id, content)