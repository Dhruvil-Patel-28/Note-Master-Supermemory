from fastapi import APIRouter, HTTPException

from .. import db, graph
from ..config import settings
from ..ingestion.extract import extract
from ..retrieval import vector
from ..retrieval.chat import grounded_answer
from ..retrieval.fts import search as fts_search
from ..retrieval.fusion import fuse
from ..schemas import (
    ChatRequest,
    ChatResponse,
    ChatSource,
    StructuredAnswer,
    StructuredField,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest):
    fts_hits = fts_search(payload.query, limit=10, include_old_versions=payload.include_history)
    vector_hits = []
    try:
        vector_hits = vector.search(payload.query, limit=10, include_old_versions=payload.include_history)
    except Exception:
        pass
    graph_hits = []
    try:
        entities = extract(payload.query)["entities"]
        graph_hits = graph.search(
            [e["name"] for e in entities],
            include_old_versions=payload.include_history,
        )
    except Exception:
        pass
    hits = fuse(fts_hits, vector_hits, graph_hits, limit=5)
    try:
        answer, found, structured = grounded_answer(payload.query, hits)
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
        structured=(
            StructuredAnswer(
                kind=structured["kind"],
                fields=[StructuredField(**f) for f in structured["fields"]],
            )
            if structured
            else None
        ),
    )