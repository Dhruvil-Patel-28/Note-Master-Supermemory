import json
import re

from fastapi import APIRouter, HTTPException

from .. import db
from ..config import settings
from ..memory.client import get_client
from ..retrieval.chat import grounded_answer, scrub_injection, transcript_fact_answer
from ..retrieval.intent import REFUSAL_ANSWER, _USER_REFERENCE_RE, classify as classify_intent
from ..schemas import (
    ChatRequest,
    ChatResponse,
    ChatSource,
    ShowDocument,
    StructuredAnswer,
    StructuredField,
)

router = APIRouter(prefix="/chat", tags=["chat"])

_SHOW_VERBS = {
    "show", "get", "open", "display", "view", "fetch", "download", "retrieve",
    "see", "find", "bring", "give", "print", "read", "pull",
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
    """A doc-requesting query says show/get/open + names a thing. There is no
    noun vocabulary to curate — a coverletter, marksheet, bonafide or any
    future doc type is detected by matching the query's content words against
    the stored labels (below). The verb gate alone decides intent; if the
    named thing matches no doc's labels, the route falls through to the LLM."""
    words = set(re.findall(r"[a-z]+", query.lower()))
    return bool(words & _SHOW_VERBS)


def _query_words(query: str) -> set[str]:
    return {
        w.replace("aadhaar", "aadhar")
        for w in re.findall(r"[a-z]+", query.lower())
        if w not in _STOPWORDS and len(w) >= 2
    }


def _label_score(qwords: set[str], raw_labels: str) -> int:
    """Word overlap between the query's content words and a doc's labels.
    Compound label tokens are split implicitly: "cover letter" matches
    "coverletter" via substring, "aadhar card" matches "aadhar_card.jpg"."""
    tokens = re.sub(r"[^a-z0-9]+", " ", raw_labels.lower().replace("aadhaar", "aadhar")).split()
    score = len(qwords & set(tokens))
    if score == 0:
        score = sum(any(w in t for t in tokens) for w in qwords)
    return score


def _find_document(query: str, hits: list[dict]) -> ShowDocument | None:
    """Pick the document a doc-intent query asks for. Hits rank by similarity,
    so the first doc hit can be a decoy — a fraud report ranking high for "get
    me my aadhar card". Score each doc by word overlap between the query's
    content words and its user-visible labels (filename/note). When the
    semantic hits don't surface the named doc (embedding space rarely ranks
    "coverletter" high), scan the latest docs' labels directly — the labels
    are the vocabulary, no noun list to grow. Nothing matching returns None
    and the route falls to the LLM."""
    if not _document_intent(query):
        return None
    qwords = _query_words(query)
    if not qwords:
        return None
    best: tuple[int, int, ShowDocument] | None = None
    scored: set[int] = set()

    def consider(row) -> None:
        nonlocal best
        doc = ShowDocument(capture_id=row["id"], filename=row["original_filename"])
        labels = f"{row['original_filename'] or ''} {row['note'] or ''}"
        score = _label_score(qwords, labels)
        if score < 1:
            return
        # Ties fall to the newest upload — "my coverletter" means the latest.
        if best is None or score > best[0] or (score == best[0] and row["id"] > best[1]):
            best = (score, row["id"], doc)

    for h in hits:
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT id, type, raw_content_ref, original_filename, note FROM captures WHERE id = ?",
                (h["capture_id"],),
            ).fetchone()
        if not row or row["type"] != "doc" or not row["raw_content_ref"]:
            continue
        scored.add(row["id"])
        consider(row)
    if best is None:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT id, type, raw_content_ref, original_filename, note FROM captures "
                "WHERE is_latest = 1 AND type = 'doc' AND raw_content_ref IS NOT NULL"
            ).fetchall()
        for row in rows:
            if row["id"] in scored:
                continue
            consider(row)
    return best[2] if best else None


def _memory_hits(query: str) -> list[dict]:
    """Retrieve from supermemory: chunk hits grouped per capture (top chunks by
    similarity), capped at the top captures, with a v1-style context budget so
    duplicated uploads can't starve the LLM context. Disabled/unreachable
    memory degrades to an empty hit list (honest not-found, no local stack)."""
    if not settings.memory_enabled:
        return []
    try:
        results = get_client().search(query, limit=_MEMORY_LIMIT, threshold=0.0)
    except Exception:
        return []
    per_capture: dict[int, list[dict]] = {}
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
def chat(payload: ChatRequest):
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
        )

    hits = _memory_hits(query)

    # Deterministic transcript facts (semester courses, total credits) are
    # parsed in Python from the capture contents — no LLM, no gates.
    det = transcript_fact_answer(query, hits)

    # Identity-fact queries (address/name/DOB) answer deterministically from
    # the stored, corroborated sensitive facts — the LLM never sees the value.
    # id_number/phone are excluded (see _FACT_QUERY_WORDS below).
    fact_key = _sensitive_fact_key(query)
    fact = _sensitive_fact_value(fact_key) if fact_key else None

    show_doc = _find_document(query, hits)
    if show_doc:
        answer = f"Here's your {show_doc.filename or 'document'} — opened in the preview."
        found = True
        structured = None
    elif det is not None:
        answer, found, structured = det
    elif fact is not None:
        _cid, value = fact
        answer = f"Your {_FACT_ANSWER_LABELS[fact_key]} is {value}."
        found = True
        structured = None
    else:
        try:
            answer, found, structured = grounded_answer(query, hits)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"chat LLM unavailable (model '{settings.ollama_model}' on {settings.ollama_host}): {exc}",
            ) from exc

    source_ids = [h["capture_id"] for h in hits]
    if fact is not None and fact[0] not in source_ids:
        source_ids.append(fact[0])
    tiers = _sensitivity_tiers(source_ids)
    hit_ids = {h["capture_id"] for h in hits}
    sources = [
        ChatSource(capture_id=h["capture_id"], snippet=h["snippet"], sensitivity_tier=tiers[h["capture_id"]])
        for h in hits
    ]
    if fact is not None and fact[0] not in hit_ids:
        sources.append(ChatSource(capture_id=fact[0], snippet="", sensitivity_tier="high"))

    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (query, retrieved_source_ids, sensitive_access) VALUES (?, ?, ?)",
            (
                payload.query,
                ",".join(str(c) for c in source_ids),
                1 if any(t == "high" for t in tiers.values()) else 0,
            ),
        )

    return ChatResponse(
        answer=answer,
        found=found,
        sources=sources,
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


# Closed vocabulary for identity-fact questions — these are FIELDS of a
# sensitive doc (extracted once at ingest into captures.sensitive_facts,
# local-only), not an open noun list. The question must also reference the
# user (_USER_REFERENCE_RE): "what is the capital" never fires this path.
# id_number and phone are deliberately NOT here: "what is my PAN number"
# answers via memory + the LLM with a structured card, and phone is
# ambiguous on a card that has none (the 3b may map any printed number
# into it). The deterministic path exists for the fields whose LABELS
# don't survive OCR (address/name/DOB) — exactly when retrieval fails.
_FACT_QUERY_WORDS = {
    "address": {
        "address", "residence", "residential", "live", "living", "stay",
        "staying", "home", "city", "hometown", "located", "location",
    },
    "name": {"name", "fullname"},
    "date_of_birth": {"dob", "birth", "birthday", "born", "birthdate"},
}
_FACT_ANSWER_LABELS = {
    "name": "name",
    "address": "address",
    "date_of_birth": "date of birth",
}


def _sensitive_fact_key(query: str) -> str | None:
    if not _USER_REFERENCE_RE.search(query):
        return None
    words = set(re.findall(r"[a-z]+", query.lower()))
    for key, vocab in _FACT_QUERY_WORDS.items():
        if words & vocab:
            return key
    return None


def _corroborate(content: str, facts: dict[str, str]) -> dict[str, str]:
    """Keep only fact values the document's own text supports. Exact (alnum)
    substring wins; otherwise a majority of the value's words (3+ chars) must
    appear in the text — a rewritten address ("Pune, MG Road" vs "MG Road,
    Pune") still corroborates, a fabricated one doesn't. The 3b can garble a
    clean PAN, so nothing uncorroborated is ever answered."""
    content_norm = re.sub(r"[^a-z0-9]+", "", (content or "").lower())
    cwords = set(re.findall(r"[a-z0-9]{3,}", (content or "").lower()))
    out: dict[str, str] = {}
    for key, value in facts.items():
        value = (value or "").strip()
        if not value:
            continue
        value_norm = re.sub(r"[^a-z0-9]+", "", value.lower())
        if value_norm and value_norm in content_norm:
            out[key] = value
            continue
        vwords = re.findall(r"[a-z0-9]{3,}", value.lower())
        if vwords and 2 * sum(1 for w in vwords if w in cwords) > len(vwords):
            out[key] = value
    return out


def _sensitive_fact_value(key: str) -> tuple[int, str] | None:
    """Newest high-tier capture holding a corroborated value for the fact key."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, content, sensitive_facts FROM captures "
            "WHERE is_latest = 1 AND sensitivity_tier = 'high' AND sensitive_facts IS NOT NULL "
            "ORDER BY id DESC"
        ).fetchall()
    for r in rows:
        try:
            facts = json.loads(r["sensitive_facts"] or "{}")
        except Exception:
            continue
        value = _corroborate(r["content"], facts).get(key)
        if value:
            return r["id"], value
    return None


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