from fastapi import APIRouter, BackgroundTasks

from .. import db
from ..ingestion.tasks import schedule_ingest
from ..schemas import FeedbackIn

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("")
def submit_feedback(payload: FeedbackIn, background: BackgroundTasks):
    query = payload.query.strip()
    if not query:
        return {"ok": False, "detail": "query must not be empty"}
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO chat_feedback (query, capture_ids, kind, note) VALUES (?, ?, ?, ?)",
            (query, ",".join(str(c) for c in payload.capture_ids), payload.kind, payload.note.strip()),
        )
    for cid in payload.capture_ids[:1]:
        try:
            schedule_ingest(background, cid)
        except Exception:
            pass
    return {"ok": True}