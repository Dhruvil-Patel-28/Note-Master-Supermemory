import json

import ollama

from ..config import settings

NOT_FOUND_ANSWER = "I don't have this in my notes."


def _client() -> ollama.Client:
    return ollama.Client(host=settings.ollama_host)


def _parse_response(raw: str) -> tuple[str, bool, dict | None]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text, text != NOT_FOUND_ANSWER and text != f'"{NOT_FOUND_ANSWER}"', None
    if data.get("kind") == "not_found":
        return NOT_FOUND_ANSWER, False, None
    answer = str(data.get("answer", text)).strip()
    found = bool(answer) and answer != NOT_FOUND_ANSWER
    if data.get("kind") == "fields":
        structured = {"kind": "fields", "fields": data.get("fields", [])}
    else:
        structured = {"kind": "prose", "fields": []}
    return answer, found, structured


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