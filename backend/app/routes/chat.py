import re

from fastapi import APIRouter, Header, HTTPException

from .. import db, graph
from ..config import settings
from ..guardrails import pin
from ..ingestion.extract import extract
from ..retrieval import vector
from ..retrieval.chat import expand_hits, grounded_answer, scrub_injection
from ..retrieval.fts import search as fts_search
from ..retrieval.fusion import fuse
from ..schemas import (
    ChatRequest,
    ChatResponse,
    ChatSource,
    ShowDocument,
    StructuredAnswer,
    StructuredField,
)

router = APIRouter(prefix="/chat", tags=["chat"])

PIN_REQUIRED_ANSWER = "This answer includes sensitive documents. Unlock with your PIN to view it."

_SHOW_VERBS = {
    "show", "get", "open", "display", "view", "fetch", "download", "retrieve",
    "see", "find", "bring", "give", "print", "read", "pull",
}
_DOC_NOUNS = {
    "resume", "cv", "document", "doc", "file", "pdf", "statement", "bill",
    "invoice", "receipt", "report", "letter", "slip", "contract", "agreement",
    "certificate", "license", "licence", "passport", "aadhaar", "aadhar", "pan",
}


def _document_intent(query: str) -> bool:
    words = set(re.findall(r"[a-z]+", query.lower()))
    return bool(words & _SHOW_VERBS) and bool(words & _DOC_NOUNS)


def _find_document(query: str, hits: list[dict]) -> ShowDocument | None:
    if not _document_intent(query):
        return None
    for h in hits:
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT type, raw_content_ref, original_filename FROM captures WHERE id = ?",
                (h["capture_id"],),
            ).fetchone()
        if row and row["type"] == "doc" and row["raw_content_ref"]:
            return ShowDocument(capture_id=h["capture_id"], filename=row["original_filename"])
    return None


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, x_pin_token: str | None = Header(default=None)):
    query = scrub_injection(payload.query)
    fts_hits = fts_search(query, limit=10, include_old_versions=payload.include_history)
    vector_hits = []
    try:
        vector_hits = vector.search(query, limit=10, include_old_versions=payload.include_history)
    except Exception:
        pass
    graph_hits = []
    try:
        entities = extract(query)["entities"]
        graph_hits = graph.search(
            [e["name"] for e in entities],
            include_old_versions=payload.include_history,
        )
    except Exception:
        pass
    hits = fuse(fts_hits, vector_hits, graph_hits, limit=5)
    context_hits = expand_hits(hits)

    tiers = _sensitivity_tiers([h["capture_id"] for h in hits])
    has_high = any(t == "high" for t in tiers.values())
    unlocked = not has_high or (x_pin_token and pin.token_valid(x_pin_token))
    sensitive_access = has_high and unlocked

    if has_high and not unlocked:
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO audit_log (query, retrieved_source_ids, sensitive_access) VALUES (?, ?, ?)",
                (payload.query, ",".join(str(h["capture_id"]) for h in hits), 0),
            )
        return ChatResponse(
            answer=PIN_REQUIRED_ANSWER,
            found=False,
            sources=[ChatSource(capture_id=h["capture_id"], snippet=h["snippet"], sensitivity_tier=tiers[h["capture_id"]]) for h in hits],
            needs_pin=True,
        )

    show_doc = _find_document(query, hits)
    if show_doc:
        answer = f"Here's your {show_doc.filename or 'document'} — opened in the preview."
        found = True
        structured = None
    else:
        try:
            answer, found, structured = grounded_answer(query, context_hits)
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
                1 if sensitive_access else 0,
            ),
        )

    return ChatResponse(
        answer=answer,
        found=found,
        sources=[
            ChatSource(capture_id=h["capture_id"], snippet=h["snippet"], sensitivity_tier=tiers[h["capture_id"]])
            for h in hits
        ],
        structured=(
            StructuredAnswer(
                kind=structured["kind"],
                fields=[StructuredField(**f) for f in structured["fields"]],
            )
            if structured
            else None
        ),
        show_document=show_doc,
    )


def _sensitivity_tiers(capture_ids: list[int]) -> dict[int, str]:
    if not capture_ids:
        return {}
    placeholders = ",".join("?" for _ in capture_ids)
    with db.get_conn() as conn:
        rows = conn.execute(
            f"SELECT id, sensitivity_tier FROM captures WHERE id IN ({placeholders})",
            capture_ids,
        ).fetchall()
    return {r["id"]: r["sensitivity_tier"] for r in rows}