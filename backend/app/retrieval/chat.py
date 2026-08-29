import json
import re

from ..config import settings
from ..observability import get_prompt
from .context import MIN_MEMORY_SIMILARITY


def scrub_injection(text: str) -> bool:
    """Detect prompt injection attempts — returns True if injection detected."""
    if not text or len(text.strip()) < 3:
        return False
    words = set(re.findall(r"\b\w+\b", text.lower()))
    content_words = words - {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "up",
        "down",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "any",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "can",
        "will",
        "just",
        "don",
        "should",
        "now",
        "d",
        "ll",
        "m",
        "o",
        "re",
        "ve",
        "y",
        "ain",
        "aren",
        "couldn",
        "didn",
        "doesn",
        "hadn",
        "hasn",
        "haven",
        "isn",
        "ma",
        "mightn",
        "mustn",
        "needn",
        "shan",
        "shouldn",
        "wasn",
        "weren",
        "won",
        "wouldn",
    }
    return len(content_words) < 2


_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "found": {"type": "boolean"},
        "kind": {"type": "string", "enum": ["fields", "prose"]},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
            },
        },
    },
    "required": ["answer", "found", "kind", "fields"],
}

_DEFAULT_ANSWER_SYSTEM = (
    "You answer using ONLY the facts in the provided context — never use outside knowledge.\n"
    "If the facts are not in the context, you MUST say so by setting found=false.\n"
    "Reply ONLY with JSON: {\"answer\": \"...\", \"found\": true|false, \"kind\": \"fields|prose\", \"fields\": []}.\n"
    "• kind=\"fields\" → structured data (name/value pairs) for enumerations, comparisons, lists.\n"
    "• kind=\"prose\" → free-text for summaries, explanations, single facts.\n"
    "Fields: use the item's OWN NAME as the key (e.g. \"Project Apollo\", \"Python\", \"Semester III\"), "
    "never generic words like \"Project\" or \"Skill\".\n"
    "Notes are facts. User's notes = truth. Never contradict them.\n"
    "Read typos char-by-char if needed (e.g. \"Pant\" = \"Pan\").\n"
    "Think silently — do not output reasoning."
)

NOT_FOUND_ANSWER = "I don't have this in my notes."


def _parse_response(raw: str) -> tuple[str, bool, dict | None]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return NOT_FOUND_ANSWER, False, None
    if not isinstance(data, dict):
        return NOT_FOUND_ANSWER, False, None
    ans = str(data.get("answer", "")).strip()
    found = bool(data.get("found", False))
    kind = data.get("kind", "prose")
    fields = data.get("fields", [])
    if not isinstance(fields, list):
        fields = []
    clean_fields = []
    for f in fields:
        if isinstance(f, dict) and "key" in f and "value" in f:
            clean_fields.append({"key": str(f["key"]), "value": str(f["value"])})
    if kind not in ("fields", "prose"):
        kind = "prose"
    structured = {"kind": kind, "fields": clean_fields} if clean_fields or kind == "fields" else {"kind": "prose", "fields": []}
    if not ans and not found:
        ans = NOT_FOUND_ANSWER
    return ans, found, structured


def _filter_fields(fields: list[dict], context: str) -> list[dict]:
    kept = []
    for f in fields:
        key = f["key"].lower()
        val = f["value"].lower()
        if key in context.lower() or val in context.lower():
            kept.append(f)
    return kept


def _wants_enumeration(query: str) -> bool:
    q = query.lower()
    return any(
        w in q
        for w in (
            "list",
            "all",
            "every",
            "each",
            "enumerate",
            "what are",
            "which",
            "how many",
            "names of",
        )
    )


def _filter_memory_results(hits: list[dict]) -> list[dict]:
    return [h for h in hits if len(h.get("snippet", "")) >= 250]


def _client():
    import ollama
    return ollama.Client(host=settings.ollama_host)


def grounded_answer(query: str, hits: list[dict]) -> tuple[str, bool, dict | None]:
    if not hits:
        return NOT_FOUND_ANSWER, False, None
    capture_ids = [h["capture_id"] for h in hits]
    context = "\n".join(
        f"[{i + 1}] (capture {h['capture_id']}): {h['snippet']}" for i, h in enumerate(hits)
    )
    enum = _wants_enumeration(query)
    enum_block = ""
    if enum:
        enum_block = (
            "\nENUMERATION QUESTION: the user wants a complete list. Use kind \"fields\" and "
            "list EVERY matching item in the context — read the whole context before answering, "
            "one field per distinct item, with the item's own NAME (project/skill/course name) as "
            "the key, never a generic word like \"Project\". If the question mentions a number, "
            "that many distinct items exist — find all of them.\n"
        )
    system = get_prompt("grounded-answer", _DEFAULT_ANSWER_SYSTEM) + enum_block + f"\nRetrieved context:\n{context}"

    def ask(extra_system: str = "") -> tuple[str, bool, dict | None]:
        response = _client().chat(
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": system + extra_system},
                {"role": "user", "content": query},
            ],
            options={"temperature": 0.1, "think": False, "num_predict": 4096},
            format=_ANSWER_SCHEMA,
        )
        return _parse_response(response["message"]["content"])

    answer, found, structured = ask()

    if found and structured and structured["fields"]:
        filtered = _filter_fields(structured["fields"], context)
        if filtered:
            structured["fields"] = filtered
        else:
            structured = {"kind": "prose", "fields": []}

    if enum and found and structured and structured.get("kind") == "fields":
        m = re.search(r"\b(\d+)\b", query)
        if m:
            want = int(m.group(1))
            got = len({f["key"].lower() for f in structured["fields"]})
            if 0 < want < 12 and got < want:
                answer, found, structured = ask(
                    f"\nCRITICAL: your previous answer listed only {got} item(s) but the "
                    f"question refers to {want}. Re-read the ENTIRE context and list every "
                    "distinct item as its own field."
                )
    return answer, found, structured


# ─── CANVAS / ARTIFACT GENERATION ────────────────────────────────────────────

_CANVAS_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "html_content": {"type": "string"},
    },
    "required": ["title", "html_content"],
}

_DEFAULT_CANVAS_SYSTEM = (
    "You build clean, well-structured HTML pages using ONLY the facts provided below.\n"
    "Never invent information — every fact on the page must come from the provided notes.\n"
    "Use inline CSS for styling: clean fonts, subtle colors, card-based layout, good spacing.\n"
    'Reply ONLY with JSON: {"title": "<page title>", "html_content": "<!DOCTYPE html>..."}\n'
    "The html_content must be a COMPLETE valid HTML document with inline <style> tags."
)


def generate_canvas(query: str, hits: list[dict]) -> dict:
    """Generate an HTML artifact from retrieved facts. No grounding check —
    this is creative synthesis of the user's own data."""
    context = "\n".join(
        f"[{i + 1}] {h['snippet']}" for i, h in enumerate(hits)
    )
    system = get_prompt("canvas-gen", _DEFAULT_CANVAS_SYSTEM) + (
        f"\n\nFacts from user's notes:\n{context}\n"
        f"Request: {query}"
    )
    response = _client().chat(
        model=settings.ollama_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": query},
        ],
        options={"temperature": 0.3, "think": False, "num_predict": 4096},
        format=_CANVAS_SCHEMA,
    )
    data = json.loads(response["message"]["content"])
    return {
        "kind": "html",
        "title": data.get("title", "Untitled"),
        "content": data.get("html_content", ""),
    }