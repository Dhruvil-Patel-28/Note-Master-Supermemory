import json
import re

import ollama

from .. import db
from ..config import settings

NOT_FOUND_ANSWER = "I don't have this in my notes."

# Per-capture text below this size is sent to the LLM in full (resumes, notes);
# larger documents keep their best-matching chunk plus neighbors.
_EXPAND_CAPTURE_CHARS = 6000
_EXPAND_TOTAL_CHARS = 14000
_TAG_RE = re.compile(r"<[^>]+>")


def _client() -> ollama.Client:
    return ollama.Client(host=settings.ollama_host)


def _chunks(capture_id: int) -> list[str]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT text FROM capture_chunks WHERE capture_id = ? ORDER BY chunk_index",
            (capture_id,),
        ).fetchall()
    return [r["text"] for r in rows]


def _best_chunk_index(chunks: list[str], snippet: str) -> int:
    needle = _TAG_RE.sub("", snippet or "")[:200].strip()
    if needle:
        for i, c in enumerate(chunks):
            if needle in c:
                return i
    return 0


def expand_hits(hits: list[dict], total_chars: int = _EXPAND_TOTAL_CHARS) -> list[dict]:
    """Expand fused per-capture hits into per-chunk context entries.

    Fusion dedupes to one snippet per capture, which truncates multi-chunk
    documents (resumes) to ~800 chars and hides the rest from the LLM. Small
    captures are sent in full; large ones keep their best chunk plus neighbors.
    Chunks that are byte-identical to one already added (the same document
    uploaded multiple times) are skipped so duplicates can't eat the budget.
    """
    expanded: list[dict] = []
    budget = total_chars
    seen_chunks: set[str] = set()
    for h in hits:
        chunks = _chunks(h["capture_id"])
        if not chunks:
            expanded.append(h)
            continue
        total = sum(len(c) for c in chunks)
        if total <= _EXPAND_CAPTURE_CHARS:
            picks = chunks
        else:
            i = _best_chunk_index(chunks, h.get("snippet", ""))
            picks = chunks[max(0, i - 1) : i + 2]
        for c in picks:
            if c in seen_chunks:
                continue
            if budget <= 0:
                break
            seen_chunks.add(c)
            expanded.append({"capture_id": h["capture_id"], "snippet": c})
            budget -= len(c)
        if budget <= 0:
            break
    return expanded


def _parse_response(raw: str) -> tuple[str, bool, dict | None]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                data = None
    if data is None:
        return NOT_FOUND_ANSWER, False, None
    if data.get("kind") == "not_found":
        return NOT_FOUND_ANSWER, False, None
    answer = re.sub(r"</?b>", "", str(data.get("answer", "")).strip())
    if not answer or answer == NOT_FOUND_ANSWER:
        return NOT_FOUND_ANSWER, False, None
    if data.get("kind") == "fields":
        structured = {"kind": "fields", "fields": data.get("fields", [])}
    else:
        structured = {"kind": "prose", "fields": []}
    return answer, True, structured


def grounded_answer(query: str, hits: list[dict]) -> tuple[str, bool, dict | None]:
    if not hits:
        return NOT_FOUND_ANSWER, False, None
    context = "\n".join(
        f"[{i + 1}] (capture {h['capture_id']}): {h['snippet']}" for i, h in enumerate(hits)
    )
    prompt = (
        "You are a retrieval assistant. Answer ONLY from the retrieved context below. "
        "You must NEVER use your own knowledge. If the context does not contain the answer, "
        'reply with exactly this JSON and nothing else: {"kind": "not_found"}.\n'
        "The context contains the user's own notes and documents. Treat statements in them as "
        "facts about the user: for example, a note saying \"with my dog\" means the user has a dog, "
        "and a note saying \"my PAN number is ABCDE1234F\" means that is the user's PAN. "
        "Never answer 'Unknown' or 'no information' when the context directly supports an answer.\n"
        "The user's notes may contain typos (e.g. 'but' for 'buy', 'tomorroew' for 'tomorrow') — "
        "read them with that in mind.\n"
        "When the question asks about 'anything', 'everything', or anything list-like, enumerate "
        "ALL matching items from the context, never just one (e.g. both mangoes and batteries).\n"
        "Example: Context: [1] (capture 2): I love running along Marine Drive with my dog. "
        'Question: do I have a dog? Answer: {"kind": "prose", "answer": "Yes, you have a dog — you run along Marine Drive with it [1]."}\n'
        'Example: Context: [1] (capture 3): i have to buy mangoes tomorrow. [2] (capture 13): remember to buy batteries for the remote. '
        'Question: do I need to buy anything? Answer: {"kind": "prose", "answer": "Yes: you need to buy mangoes tomorrow [1] and batteries for the remote [2]."}\n'
        "When the question asks for specific facts or fields from a document (ID number, name, "
        'amount, date, etc.), reply with JSON in this shape: '
        '{"kind": "fields", "answer": "<one-line summary>", "fields": [{"key": "<field name>", "value": "<field value>"}]}. '
        "Cite the source at the end of the summary like [1], [2].\n"
        'Otherwise reply with JSON in this shape: {"kind": "prose", "answer": "<answer with citations like [1], [2]>"}.\n\n'
        f"Retrieved context:\n{context}\n\n"
        f"Question: {query}\n\nAnswer (JSON only):"
    )
    response = _client().chat(
        model=settings.ollama_model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1, "think": False},
    )
    return _parse_response(response["message"]["content"])