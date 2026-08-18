from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import db, graph, storage
from ..ingestion.extractors import SUPPORTED_EXTENSIONS
from ..ingestion.pipeline import create_capture
from ..ingestion.tasks import schedule_ingest
from ..schemas import CaptureOut, CaptureUpdateIn, TextCaptureIn

router = APIRouter(prefix="/captures", tags=["captures"])


def _to_out(row) -> CaptureOut:
    return CaptureOut(
        id=row["id"],
        type=row["type"],
        content=row["content"],
        raw_content_ref=row["raw_content_ref"],
        original_filename=row["original_filename"],
        note=row["note"],
        status=row["status"],
        error=row["error"],
        sensitivity_tier=row["sensitivity_tier"],
        document_group_id=row["document_group_id"],
        version_number=row["version_number"],
        is_latest=bool(row["is_latest"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _get_capture(capture_id: int):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="capture not found")
    return row


@router.post("/text", response_model=CaptureOut)
def create_text_capture(payload: TextCaptureIn, background: BackgroundTasks):
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="content must not be empty")
    capture_id = create_capture("text", content=content)
    schedule_ingest(background, capture_id)
    return _to_out(_get_capture(capture_id))


@router.post("/file", response_model=CaptureOut)
def create_file_capture(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    note: str | None = Form(None),
    document_group_id: int | None = None,
):
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported file type {ext!r}; supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=422, detail="empty file")
    rel = storage.save_upload(file.filename, data)
    capture_id = create_capture(
        "doc",
        raw_content_ref=rel,
        original_filename=file.filename,
        note=note.strip() if note else None,
        document_group_id=document_group_id,
    )
    schedule_ingest(background, capture_id)
    return _to_out(_get_capture(capture_id))


AUDIO_EXTENSIONS = {".m4a", ".webm", ".wav", ".mp3", ".aiff", ".ogg", ".opus"}


@router.post("/audio", response_model=CaptureOut)
def create_audio_capture(background: BackgroundTasks, file: UploadFile = File(...)):
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported audio type {ext!r}; supported: {sorted(AUDIO_EXTENSIONS)}",
        )
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=422, detail="empty file")
    rel = storage.save_upload(file.filename, data)
    capture_id = create_capture("voice", raw_content_ref=rel, original_filename=file.filename)
    schedule_ingest(background, capture_id)
    return _to_out(_get_capture(capture_id))


@router.get("", response_model=list[CaptureOut])
def list_captures(include_old_versions: bool = False):
    clause = "" if include_old_versions else "WHERE is_latest = 1"
    with db.get_conn() as conn:
        rows = conn.execute(f"SELECT * FROM captures {clause} ORDER BY created_at DESC, id DESC").fetchall()
    return [_to_out(r) for r in rows]


@router.get("/{capture_id}", response_model=CaptureOut)
def get_capture(capture_id: int):
    return _to_out(_get_capture(capture_id))


@router.patch("/{capture_id}", response_model=CaptureOut)
def update_capture(capture_id: int, payload: CaptureUpdateIn, background: BackgroundTasks):
    row = _get_capture(capture_id)
    content = payload.content.strip() if payload.content else None
    note = payload.note.strip() if payload.note else None
    if content is None and note is None:
        raise HTTPException(status_code=422, detail="nothing to update")
    with db.get_conn() as conn:
        if content is not None:
            if not content:
                raise HTTPException(status_code=422, detail="content must not be empty")
            conn.execute(
                "UPDATE captures SET content = ?, note = ?, status = 'queued', error = NULL WHERE id = ?",
                (content, note, capture_id),
            )
        else:
            conn.execute(
                "UPDATE captures SET note = ? WHERE id = ?",
                (note, capture_id),
            )
    if content is not None:
        schedule_ingest(background, capture_id)
    else:
        from ..ingestion.pipeline import rebuild_fts

        rebuild_fts(capture_id)
    return _to_out(_get_capture(capture_id))


@router.delete("/{capture_id}", status_code=204)
def delete_capture(capture_id: int):
    row = _get_capture(capture_id)
    from ..memory.sync import forget_capture

    forget_capture(capture_id)
    graph.delete_capture(capture_id)
    with db.get_conn() as conn:
        conn.execute(
            "DELETE FROM chunks_vec WHERE rowid IN (SELECT id FROM capture_chunks WHERE capture_id = ?)",
            (capture_id,),
        )
        conn.execute("DELETE FROM captures_fts WHERE rowid = ?", (capture_id,))
        conn.execute("DELETE FROM captures WHERE id = ?", (capture_id,))
        if row["document_group_id"] is not None:
            conn.execute(
                """UPDATE captures SET is_latest = 1
                   WHERE document_group_id = ? AND id = (
                       SELECT id FROM captures WHERE document_group_id = ?
                       ORDER BY version_number DESC LIMIT 1
                   )""",
                (row["document_group_id"], row["document_group_id"]),
            )
    if row["raw_content_ref"]:
        storage.delete_file(row["raw_content_ref"])


@router.post("/{capture_id}/restore", response_model=CaptureOut)
def restore_capture(capture_id: int):
    row = _get_capture(capture_id)
    if row["document_group_id"] is None:
        raise HTTPException(status_code=422, detail="capture has no version history to restore")
    if row["is_latest"]:
        raise HTTPException(status_code=409, detail="capture is already the latest version")
    with db.get_conn() as conn:
        group_rows = conn.execute(
            "SELECT id FROM captures WHERE document_group_id = ?",
            (row["document_group_id"],),
        ).fetchall()
        group_ids = [r["id"] for r in group_rows]
        conn.execute(
            "UPDATE captures SET is_latest = 0 WHERE document_group_id = ?",
            (row["document_group_id"],),
        )
        conn.execute(
            "UPDATE captures SET is_latest = 1 WHERE id = ?",
            (capture_id,),
        )
    graph.restore_capture(capture_id, group_ids)
    from ..memory.sync import sync_capture

    sync_capture(capture_id)
    return _to_out(_get_capture(capture_id))


@router.get("/{capture_id}/audio")
def get_audio(capture_id: int):
    row = _get_capture(capture_id)
    if row["type"] != "voice" or not row["raw_content_ref"]:
        raise HTTPException(status_code=404, detail="no audio for this capture")
    path = Path(storage.resolve_path(row["raw_content_ref"]))
    if not path.exists():
        raise HTTPException(status_code=404, detail="audio file missing")
    media_type = {".m4a": "audio/mp4", ".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".aiff": "audio/aiff"}.get(path.suffix.lower(), "audio/webm")
    return FileResponse(path, media_type=media_type)


_FILE_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
}


@router.get("/{capture_id}/file")
def get_original_file(capture_id: int):
    row = _get_capture(capture_id)
    if row["type"] != "doc" or not row["raw_content_ref"]:
        raise HTTPException(status_code=404, detail="no original file for this capture")
    path = Path(storage.resolve_path(row["raw_content_ref"]))
    if not path.exists():
        raise HTTPException(status_code=404, detail="file missing from disk")
    return FileResponse(path, media_type=_FILE_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"))


@router.get("/history/{document_group_id}", response_model=list[CaptureOut])
def list_document_history(document_group_id: int):
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM captures WHERE document_group_id = ? ORDER BY version_number DESC",
            (document_group_id,),
        ).fetchall()
    return [_to_out(r) for r in rows]