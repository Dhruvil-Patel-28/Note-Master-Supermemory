from fastapi import APIRouter, HTTPException

from .. import db
from ..config import settings
from ..retrieval.chat import grounded_answer
from ..retrieval.fts import search
from ..schemas import ChatRequest, ChatResponse, ChatSource

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest):
    hits = search(payload.query, include_old_versions=payload.include_history)
    try:
        answer, found = grounded_answer(payload.query, hits)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"chat LLM unavailable (model '{settings.ollama_model}' on {settings.ollama_host}): {exc}",
        ) from exc

    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (query, retrieved_source_ids, sensitive_access) VALUES (?, ?, ?)",
            (
                payload.query,
                ",".join(str(h["capture_id"]) for h in hits),
                0,
            ),
        )

    return ChatResponse(
        answer=answer,
        found=found,
        sources=[ChatSource(capture_id=h["capture_id"], snippet=h["snippet"]) for h in hits],
    )