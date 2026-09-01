"""Retrieval core: everything that assembles LLM context from the local
ChromaDB vector store.

Extracted from routes/chat.py so the HTTP layer keeps only guardrails and
transport concerns, and so the agentic loop (retrieval.agent) can compose
these primitives directly. Behavior is identical to the pre-extraction code.
"""
import os
import re

from .. import db
from ..config import settings

_MEMORY_TOP_CAPTURES = 5
_MEMORY_CHUNKS_PER_CAPTURE = 4
# Enumeration questions ("which are the 3 projects", "how many courses") need
# breadth — every matching fact — so they get expanded per-capture slots.
_MEMORY_CHUNKS_PER_CAPTURE_ENUM = 6
_CONTEXT_BUDGET = 16000
# Raw chunks smaller than this are headers/dividers ("resume\nResume_D.pdf\n
 # ## Education") — near-zero information, yet they outrank fact-bearing
# results on label-word similarity. Demoted to the back of a capture's queue.
_MIN_FULL_CHUNK_CHARS = 250
# A label-matched document counts as "represented" only if this much of it
# reached the context; below that, the pin injects fuller content.
_SPARSE_REPRESENTATION_CHARS = 800
_PIN_SNIPPET_CHARS = 4000
# Honest not-found protection: dense retrieval ranks EVERY chunk for any query
# (threshold 0), so out-of-vocabulary questions ("do i own a zebra") would
# drag unrelated chunks — including a high-tier PAN note — into the top-5 and
# gate an innocent query. The floor is set below the observed relevant band.
MIN_MEMORY_SIMILARITY = float(os.getenv("MIN_MEMORY_SIMILARITY", "0.38"))
# Chunks whose text is majority whitespace (table/script formatting dumps) are
# near-zero information yet rank artificially high — tiny stage directions and
# empty table cells score above real content on unrelated queries. Drop them.
_MAX_WHITESPACE_RATIO = 0.6

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


def _match_document(query: str) -> dict | None:
    """Best latest capture whose labels (filename/note) overlap the query's
    content words — the labels ARE the vocabulary, no noun list. Unlike
    show-document intent this needs no show-verb: a content question that
    names a document must draw on that document even when semantic ranking
    surfaces other captures. Ties fall to the newest upload."""
    qwords = _query_words(query)
    if not qwords:
        return None
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, content, original_filename, note FROM captures WHERE is_latest = 1"
        ).fetchall()
    best: dict | None = None
    best_score = 0
    for row in rows:
        labels = f"{row['original_filename'] or ''} {row['note'] or ''}"
        score = _label_score(qwords, labels)
        if score < 1:
            continue
        if best is None or score > best_score or (score == best_score and row["id"] > best["id"]):
            best = row
            best_score = score
    return best


_ENUM_INTENT_RE = re.compile(
    r"\bhow\s+many\b|\blist\b|\ball\s+(?:my|the|of)\b|\benumerate\b"
    r"|\b(?:which|what)\s+are\b",
    re.IGNORECASE,
)


def _wants_enumeration(query: str) -> bool:
    """Listing questions ("which are the 3 projects", "how many courses") need
    breadth — every matching fact — so they get expanded per-capture slots."""
    return bool(_ENUM_INTENT_RE.search(query))


def _slot_sort_key(r: dict) -> tuple[int, float]:
    """Sort results within a capture's slot queue: fact-bearing results first
    (by similarity), tiny raw chunks last regardless of similarity."""
    tiny_raw = r.get("kind") == "chunk" and len(r.get("content", "")) < _MIN_FULL_CHUNK_CHARS
    return (1 if tiny_raw else 0, -r.get("similarity", 0.0))


def _memory_hits(query: str) -> list[dict]:
    """Retrieve from the local ChromaDB vector store: embed query →
    nearest-neighbour search → group per capture with slots."""
    if not settings.memory_enabled:
        return []
    return _vector_hits(query)


def _vector_hits(query: str) -> list[dict]:
    """ChromaDB path: embed query → search → group per capture with slots."""
    from ..embeddings.provider import embed
    from .vector_store import search

    q_vec = embed([query])[0]
    # Pull a generous candidate pool — ChromaDB's similarity scale here is
    # compressed (real answers can sit at 0.38-0.45, below whitespace noise at
    # 0.5), so a small k would drop the answer before dedup/filtering runs.
    results = search(q_vec, k=100)
    if not results:
        return []
    # Dedupe near-identical chunks first: the same note content is frequently
    # uploaded as N separate captures (each is_latest, own group), so without
    # this a single note floods every per-capture slot and nothing else — the
    # invoice, directory, catalog — ever surfaces. Keep the best-scoring copy
    # of each unique normalized text.
    seen_text: dict[str, dict] = {}
    for r in results:
        if r.get("similarity", 0.0) < MIN_MEMORY_SIMILARITY:
            continue
        snippet = r["snippet"]
        if not snippet:
            continue
        # Drop whitespace-dominated formatting dumps (tables/scripts) — they
        # rank above real content but carry ~zero information.
        ws = sum(1 for c in snippet if c.isspace()) / len(snippet)
        if ws > _MAX_WHITESPACE_RATIO:
            continue
        norm = re.sub(r"\s+", " ", snippet).strip().lower()
        if not norm:
            continue
        prev = seen_text.get(norm)
        if prev is None or r["similarity"] > prev["similarity"]:
            seen_text[norm] = r
    per_capture: dict[int, list[dict]] = {}
    for r in seen_text.values():
        cid = r["capture_id"]
        per_capture.setdefault(cid, []).append({
            "content": r["snippet"],
            "kind": "chunk",
            "metadata": {"capture_id": str(cid)},
            "similarity": r["similarity"],
        })
    if not per_capture:
        return []
    slots = (
        _MEMORY_CHUNKS_PER_CAPTURE_ENUM
        if _wants_enumeration(query)
        else _MEMORY_CHUNKS_PER_CAPTURE
    )
    hits: list[dict] = []
    budget = _CONTEXT_BUDGET
    for cid in sorted(
        per_capture,
        key=lambda c: max(x["similarity"] for x in per_capture[c]),
        reverse=True,
    )[:_MEMORY_TOP_CAPTURES]:
        for r in sorted(per_capture[cid], key=_slot_sort_key)[:slots]:
            if budget <= 0:
                break
            hits.append({
                "capture_id": cid,
                "snippet": r["content"],
                "similarity": r["similarity"],
                "source": "vector-chunk",
            })
            budget -= len(r["content"])
        if budget <= 0:
            break
    return hits


def _stem(w: str) -> str:
    """Trivial plural fold so grounding matches 'projects' against 'project'
    (and vice versa) without letting genuine '-ss/-us' words collapse."""
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def _apply_document_pin(hits: list[dict], matched: dict | None) -> list[dict]:
    """Ranking luck must not decide how well a label-matched document is
    represented. Presence alone isn't enough: a doc can make it into hits via
    one tiny header chunk while its actual facts rank below the per-capture
    slot cut (the "which are my projects" bug). If the matched document's
    retrieved representation is sparse — or absent — prepend fuller content.
    Well-represented documents are left untouched."""
    if not matched:
        return hits
    retrieved = sum(len(h["snippet"]) for h in hits if h["capture_id"] == matched["id"])
    if retrieved >= _SPARSE_REPRESENTATION_CHARS:
        return hits
    return [
        {
            "capture_id": matched["id"],
            "snippet": (matched["content"] or "")[:_PIN_SNIPPET_CHARS],
            "similarity": 1.0,
            "source": "pin",
        }
    ] + hits


def build_context(query: str) -> list[dict]:
    """Everything the LLM will see for this question under SINGLE-SHOT
    retrieval: vector search over ChromaDB chunks, then the sparse-
    representation pin guarantees a label-matched document is represented.
    The agentic loop (retrieval.agent) composes these same primitives across
    multiple rounds; this function remains the non-agentic baseline and the
    seam the retrieval-quality suite exercises."""
    hits = _memory_hits(query)
    matched = _match_document(query)
    matched = dict(matched) if matched else None
    return _apply_document_pin(hits, matched)
