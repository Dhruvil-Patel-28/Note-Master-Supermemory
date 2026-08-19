import re

from fastapi import APIRouter, Header, HTTPException

from .. import db
from ..config import settings
from ..guardrails import pin
from ..memory.client import get_client
from ..retrieval.chat import grounded_answer, scrub_injection, transcript_fact_answer
from ..retrieval.intent import REFUSAL_ANSWER, classify as classify_intent
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

_MEMORY_LIMIT = 30
_MEMORY_TOP_CAPTURES = 5
_MEMORY_CHUNKS_PER_CAPTURE = 3
_CONTEXT_BUDGET = 14000
# Honest not-found protection: supermemory ranks EVERY doc for any query
# (threshold 0), so out-of-vocabulary questions ("do i own a zebra") would
# drag unrelated chunks — including a high-tier PAN note — into the top-5 and
# gate an innocent query. v1's MIN_COSINE_DISTANCE=0.5 did the same job; the
# floor is set below the observed relevant band (0.44-0.55, fact docs higher).
MIN_MEMORY_SIMILARITY = 0.45

# High-tier gate-anchor scan (below) and v1's FTS shared the same stopword
# set — inlined here since the FTS module is retired.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "he", "i", "in", "is", "it", "its", "me", "much", "my", "of", "on",
    "or", "that", "the", "this", "to", "was", "we", "were", "what", "will",
    "with", "you", "your",
    "about", "any", "can", "could", "did", "do", "does", "get", "going",
    "here", "how", "just", "know", "like", "please", "say", "said", "should",
    "show", "tell", "there", "want", "when", "where", "which", "who", "why",
    "would",
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


def _high_tier_local_matches(query: str) -> list[dict]:
    """Lexical scan of latest high-tier captures (local-only by design, never
    in supermemory). Word-overlap on the query's content terms — the same
    overlap the PIN gate has always relied on; single-char and stopwords are
    dropped so "a" / "in" can't gate on every high doc."""
    qwords = {
        w for w in re.findall(r"[a-z]+", query.lower()) if len(w) >= 2 and w not in _STOPWORDS
    }
    if not qwords:
        return []
    rows = []
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, content, note, original_filename FROM captures "
            "WHERE is_latest = 1 AND sensitivity_tier = 'high'"
        ).fetchall()
    hits = []
    for r in rows:
        text = " ".join(x or "" for x in (r["content"], r["note"], r["original_filename"]))
        cwords = {
            w for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 2 and w not in _STOPWORDS
        }
        if qwords & cwords:
            content = (r["content"] or "").strip()
            if content:
                hits.append({"capture_id": r["id"], "content": content[:600], "similarity": 1.0})
    return hits


def _memory_hits(query: str) -> list[dict]:
    """Retrieve from supermemory: chunk hits grouped per capture (top chunks by
    similarity), capped at the top captures, with a v1-style context budget so
    duplicated uploads can't starve the LLM context. Disabled/unreachable
    memory degrades to an empty hit list (honest not-found, no local stack).

    High-tier captures never enter memory, so a "what is my pan number" query
    would otherwise rank a low-tier note ("my other number is 1 2 3 4 5 6 7")
    and answer without ever hitting the PIN gate. A local lexical scan of
    latest high-tier captures re-attaches them as gate anchors (similarity 1.0
    — the floor never drops them), restoring v1's gate semantics: the query is
    gated, and after unlock the capture's content is in the LLM context."""
    if not settings.memory_enabled:
        return []
    hits = _high_tier_local_matches(query)
    try:
        results = get_client().search(query, limit=_MEMORY_LIMIT, threshold=0.0)
    except Exception:
        return hits
    per_capture: dict[int, list[dict]] = {}
    for h in hits:
        per_capture.setdefault(h["capture_id"], []).append(h)
    for r in results:
        if r.get("similarity", 0.0) < MIN_MEMORY_SIMILARITY:
            continue
        try:
            cid = int(r["metadata"].get("capture_id", ""))
        except (TypeError, ValueError):
            continue
        per_capture.setdefault(cid, []).append(r)
    if not per_capture:
        return []
    hits: list[dict] = []
    budget = _CONTEXT_BUDGET
    for cid in sorted(
        per_capture,
        key=lambda c: max(x["similarity"] for x in per_capture[c]),
        reverse=True,
    )[:_MEMORY_TOP_CAPTURES]:
        for r in sorted(per_capture[cid], key=lambda x: -x["similarity"])[:_MEMORY_CHUNKS_PER_CAPTURE]:
            if budget <= 0:
                break
            hits.append({"capture_id": cid, "snippet": r["content"], "similarity": r["similarity"]})
            budget -= len(r["content"])
        if budget <= 0:
            break
    return hits


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, x_pin_token: str | None = Header(default=None)):
    query = scrub_injection(payload.query)
    intent = classify_intent(query)
    if intent in ("code", "general"):
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO audit_log (query, retrieved_source_ids, sensitive_access) VALUES (?, ?, ?)",
                (payload.query, "", 0),
            )
        return ChatResponse(
            answer=REFUSAL_ANSWER,
            found=False,
            sources=[],
            needs_pin=False,
        )

    hits = _memory_hits(query)

    tiers = _sensitivity_tiers([h["capture_id"] for h in hits])
    has_high = any(t == "high" for t in tiers.values())
    unlocked = not has_high or (x_pin_token and pin.token_valid(x_pin_token))
    sensitive_access = has_high and unlocked

    # Deterministic transcript facts (semester courses, total credits) are
    # parsed in Python from the capture contents — the answer never touches the
    # LLM and never draws on sensitive captures, so an unrelated high-tier hit
    # dragged in by vector noise must not gate them (e.g. an Aadhaar note
    # ranking 4th for "how many credits have I earned").
    det = transcript_fact_answer(query, hits)

    if has_high and not unlocked and det is None:
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
    elif det is not None:
        answer, found, structured = det
    else:
        try:
            answer, found, structured = grounded_answer(query, hits)
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