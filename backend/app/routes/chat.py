import json
import re

from fastapi import APIRouter, Header, HTTPException

from .. import db, graph
from ..config import settings
from ..guardrails import pin
from ..ingestion.extract import extract
from ..retrieval import vector
from ..retrieval.chat import (
    _client,
    _extract_json,
    expand_hits,
    grounded_answer,
    scrub_injection,
    transcript_fact_answer,
)
from ..retrieval.fts import _STOPWORDS, search as fts_search
from ..retrieval.fusion import fuse
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


_ACADEMIC_WORDS = {
    "semester", "sem", "term", "trimester", "cgpa", "gpa", "marksheet",
    "transcript", "grade", "grades", "result", "results", "course", "courses",
    "academic", "marks", "score", "credit", "credits",
}
# Transcripts label semesters with bare digits ("2 / DIGITAL ELECTRONICS / ...")
# — no "semester" word to match. Academic-intent queries get these doc-ish terms
# appended to the FTS query so the transcript surfaces.
_ACADEMIC_EXTRA_TERMS = ["transcript", "marksheet"]


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
    query_words = set(re.findall(r"[a-z]+", query.lower()))
    fts_query = query
    if query_words & _ACADEMIC_WORDS:
        fts_query = " ".join([query] + _ACADEMIC_EXTRA_TERMS)
    fts_hits = fts_search(fts_query, limit=10, include_old_versions=payload.include_history)
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
    # Lexical-gap cure: when retrieval comes back empty or with no matching
    # terms, ask the LLM what words the user's notes might use for this concept
    # and re-run FTS with the validated ones — the general fix for "where do I
    # study" (the notes say 'institute', never 'study'), no per-case lists.
    if not hits or not any("<b>" in h["snippet"] for h in hits):
        anchors = _expand_anchors(query)
        if anchors:
            fts_hits = fts_search(
                " ".join([query] + anchors),
                limit=10,
                include_old_versions=payload.include_history,
            )
            hits = fuse(fts_hits, vector_hits, graph_hits, limit=5)
    context_hits = expand_hits(hits)

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


_ANCHOR_SYSTEM = (
    "A user asked a question about their own personal notes. "
    "The following words actually appear in the user's notes: {vocab}\n"
    "Pick up to 5 words FROM THAT LIST that could relate to the question's concept — "
    'the words the user\'s notes would use. Reply ONLY with JSON: {{"terms": ["word1", "word2", ...]}}.\n'
    'Example: Question: "where do i study" -> {{"terms": ["institute", "college", "education"]}}\n'
    'Example: Question: "who do i work for" -> {{"terms": ["work", "company"]}}\n'
)

_WORD_RE = re.compile(r"[^\w\s]")


def _vocabulary(limit: int = 60) -> list[str]:
    """Content words actually present in the user's latest notes — sampled from
    each capture's opening window (headers/first lines carry the distinctive
    facts: institute name, work, contact) so long bodies of repeated codes and
    duplicated uploads don't drown them out."""
    merged: set[str] = set()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT content FROM captures WHERE is_latest = 1 ORDER BY id DESC LIMIT 20"
        ).fetchall()
    for r in rows:
        window = r["content"][:300]
        counts: dict[str, int] = {}
        for w in _WORD_RE.sub(" ", window.lower()).split():
            if len(w) >= 3 and w not in _STOPWORDS and not w.isdigit():
                counts[w] = counts.get(w, 0) + 1
        if counts:
            top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            merged |= {w for w, _ in top}
    return sorted(merged)[:limit]


def _expand_anchors(query: str) -> list[str]:
    """Have the LLM pick words the user's notes might use for this concept,
    restricted to the user's actual vocabulary — hallucinated anchors can't
    even be suggested, and anything picked is index-verified by construction."""
    vocab = _vocabulary()
    if not vocab:
        return []
    try:
        raw = _client().chat(
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": _ANCHOR_SYSTEM.format(vocab=", ".join(vocab))},
                {"role": "user", "content": query},
            ],
            options={"temperature": 0.1, "think": False, "num_predict": 512},
        )["message"]["content"]
        payload = json.loads(_extract_json(raw) or "{}")
        terms = payload.get("terms") or []
    except Exception:
        return []
    if not isinstance(terms, list):
        return []
    valid: list[str] = []
    seen: set[str] = set()
    for t in terms:
        t = str(t).strip().lower()
        if t in vocab and t not in seen:
            valid.append(t)
            seen.add(t)
    return valid[:5]