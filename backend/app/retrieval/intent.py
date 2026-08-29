import json
import re

from ..config import settings
from ..observability import get_prompt
from .chat import _client

REFUSAL_ANSWER = "I can only answer questions about your own notes and documents — I don't have general knowledge or coding abilities."

_INTENT_WHITELIST = {"notes", "code", "general", "hybrid", "unknown", "create"}

# Deterministic hint fallback ONLY — used when the LLM call itself fails, never
# to override the LLM. Code questions are the dangerous class (they used to
# produce garbage from the notes-cage), so a failed classifier still refuses them.
_CODE_HINTS = re.compile(
    r"\b(print|println|function|syntax|code|script|program|algorithm|loop|variable|"
    r"debug|exception|compiler|helloworld|hello\s*world|"
    r"write\s+a\s+(?:function|program|script)|"
    r"in\s+(?:python|java|javascript|js|sql|cpp|c\+\+|golang|go|rust|bash|typescript))\b",
    re.IGNORECASE,
)

_CREATE_HINTS = re.compile(
    r"\b(make|create|build|generate|design|compile|prepare|draft|write\s*up|put\s*together)\b"
    r".*\b(page|report|portfolio|summary|overview|dashboard|html|document|file)\b",
    re.IGNORECASE,
)

_CLASSIFIER_SYSTEM = get_prompt("intent-classifier", (
    "You classify a user's question into exactly one intent. Reply ONLY with JSON: "
    '{"intent": "<one of notes|code|general|hybrid|unknown|create>"}.\n\n'
    "DEFINITIONS:\n"
    "notes = asking about the user's own life, notes or documents: their name, institute, courses, PAN, "
    "car, bills, plans, trips, possessions, files, memories. Almost every 'do i / did i / where do "
    "i / what is my / have i' question is notes.\n"
    "create = the user wants you to BUILD or GENERATE something from their notes: a page, a summary, "
    "a report, a portfolio, an overview. Look for verbs like: make, create, build, generate, design, "
    "compile, prepare, draft, write up, put together. This is about CREATING OUTPUT, not just answering.\n"
    'code = asking for code or programming help ("print my name in python", "write a function").\n'
    'general = about the world or knowledge at large, NOT about the user at all ("what is the capital of france", "what is 2+2").\n'
    'hybrid = about the user\'s notes AND needing programming knowledge ("what python skills do i have").\n'
    'unknown = you cannot tell.\n\n'
    "RULES: When in doubt, choose notes. But if the user wants to CREATE something, always choose create.\n\n"
    "EXAMPLES:\n"
    'Example: "which were my 2nd sem courses" -> {"intent": "notes"}\n'
    'Example: "where do i study" -> {"intent": "notes"}\n'
    'Example: "where do i work" -> {"intent": "notes"}\n'
    'Example: "where did i go in december" -> {"intent": "notes"}\n'
    'Example: "car registration number" -> {"intent": "notes"}\n'
    'Example: "electricity bill amount" -> {"intent": "notes"}\n'
    'Example: "summer vacation destination" -> {"intent": "notes"}\n'
    'Example: "what is my pan number" -> {"intent": "notes"}\n'
    'Example: "print my name in python" -> {"intent": "code"}\n'
    'Example: "write a function to reverse a string" -> {"intent": "code"}\n'
    'Example: "what is the capital of france" -> {"intent": "general"}\n'
    'Example: "what is 2+2" -> {"intent": "general"}\n'
    'Example: "what python skills do i have" -> {"intent": "hybrid"}\n'
    'Example: "asdfgh" -> {"intent": "unknown"}\n'
    'Example: "what is the mummy a tale of" -> {"intent": "notes"}\n'
    'Example: "what happens in the book i uploaded" -> {"intent": "notes"}\n'
    'Example: "summarize my pdf" -> {"intent": "notes"}\n'
    'Example: "make me a project summary page" -> {"intent": "create"}\n'
    'Example: "build me a portfolio from my resume" -> {"intent": "create"}\n'
    'Example: "create a summary of my notes" -> {"intent": "create"}\n'
    'Example: "make an HTML page with my employee data" -> {"intent": "create"}\n'
    'Example: "generate a report of my finances" -> {"intent": "create"}\n'
    'Example: "design a dashboard with my expenses" -> {"intent": "create"}\n'
))

# Safety net, not a primary: a "general" answer that still concerns the user
# ("where do i X", "my Y") must not refuse the notes path. Code hints win.
_USER_REFERENCE_RE = re.compile(
    r"\b(my|mine|me|myself|i'?m|i\s+(?:have|am|was|had|want|need)|"
    r"(?:do|did|have|am|was)\s+i|where\s+do\s+i)\b",
    re.IGNORECASE,
)

_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["notes", "code", "general", "hybrid", "unknown", "create"],
        }
    },
    "required": ["intent"],
}


def classify(query: str) -> str:
    """Route a question: notes path vs clean refusal (code/general).

    The enum grammar constrains decoding to the whitelist, so no salvage is
    needed. Any failure (LLM down, runtime dropped the constraint) falls back
    to 'notes' — the pre-existing behavior — unless the query has strong code
    hints, which are refused instead of producing garbage.
    """
    # Deterministic override: create intent (small models often miss it)
    if _CREATE_HINTS.search(query):
        return "create"
    try:
        raw = _client().chat(
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": _CLASSIFIER_SYSTEM},
                {"role": "user", "content": query},
            ],
            options={"temperature": 0.1, "think": False, "num_predict": 64},
            format=_INTENT_SCHEMA,
        )["message"]["content"]
        intent = json.loads(raw).get("intent")
        if intent in _INTENT_WHITELIST:
            if intent == "general" and _USER_REFERENCE_RE.search(query) and not _CODE_HINTS.search(query):
                return "notes"
            return intent
    except Exception:
        pass
    if _CODE_HINTS.search(query):
        return "code"
    return "notes"
