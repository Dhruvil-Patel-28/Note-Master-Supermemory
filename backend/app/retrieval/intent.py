import json
import re

from ..config import settings
from ..observability import get_prompt
from .chat import _client

REFUSAL_ANSWER = "I can only answer questions about your own notes and documents — I don't have general knowledge or coding abilities."

_INTENT_WHITELIST = {"notes", "code", "general", "hybrid", "unknown"}

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

_CLASSIFIER_SYSTEM = get_prompt("intent-classifier", (
    "You classify a user's question into exactly one intent. Reply ONLY with JSON: "
    '{"intent": "<one of notes|code|general|hybrid|unknown>"}.\n'
    "notes = about the user's own life, notes or documents: their name, institute, courses, PAN, "
    "car, bills, plans, trips, possessions, files, memories. Almost every 'do i / did i / where do "
    "i / what is my / have i' question is notes.\n"
    'code = asking for code or programming help ("print my name in python", "write a function").\n'
    'general = about the world or knowledge at large, NOT about the user at all ("what is the capital of france", "what is 2+2", "how tall is mount everest").\n'
    'hybrid = about the user\'s notes AND needing programming knowledge ("what python skills do i have").\n'
    'unknown = you cannot tell.\n'
    "When in doubt, choose notes.\n"
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
            "enum": ["notes", "code", "general", "hybrid", "unknown"],
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
