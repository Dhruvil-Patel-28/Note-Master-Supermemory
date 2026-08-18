import json
import re

import ollama

from ..config import settings
from ..retrieval.chat import _extract_cgpa, _extract_credits, _parse_transcript_sections

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s-]{8,15}\d")
_INSTITUTE_KEYWORDS = ("institute", "university", "college", "academy", "school")
_HEADER_BLACKLIST = {
    "education", "projects", "experience", "skills", "summary", "objective",
    "certifications", "achievements", "languages", "interests", "contact",
}

_ORDINALS = {
    1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th",
    6: "6th", 7: "7th", 8: "8th",
}


def _institute(text: str) -> str | None:
    """First occurrence of an institute/university/college phrase, widened to
    sentence-ish boundaries. Deterministic — the 3b model reads 'T echnology'
    (space inside the word) or drops the header entirely."""
    for kw in _INSTITUTE_KEYWORDS:
        m = re.search(rf"\b{kw}\b", text, re.IGNORECASE)
        if not m:
            continue
        start = max(0, m.start() - 60)
        end = min(len(text), m.end() + 60)
        phrase = re.sub(r"\s+", " ", text[start:end]).strip(" \t\n,:;|/")
        if len(phrase) < 160:
            return phrase
    return None


def transcript_facts(content: str) -> list[str]:
    facts = []
    inst = _institute(content)
    if inst:
        facts.append(f"The user studies at {inst}.")
    for label, courses in _parse_transcript_sections(content):
        listing = "; ".join(f"{code} {name}" for code, name in courses)
        ordinal = _ORDINALS.get(label, f"{label}th")
        facts.append(f"The user's {ordinal} semester courses are: {listing}.")
    credits = _extract_credits(content)
    if credits:
        facts.append(f"The user has earned {credits} credits in total.")
    cgpa = _extract_cgpa(content)
    if cgpa:
        facts.append(f"The user's CGPA is {cgpa}.")
    return facts


def _resume_name(content: str) -> str | None:
    for line in content.splitlines()[:8]:
        line = line.strip(" \t\n|/")
        if not line:
            continue
        words = line.split()
        if len(words) < 2 or len(words) > 4:
            continue
        if any(w.lower() in _HEADER_BLACKLIST for w in words):
            continue
        if any(ch.isdigit() for ch in line):
            continue
        if all(w[:1].isupper() for w in words if w[:1].isalpha()):
            return line
    return None


def resume_facts(content: str) -> list[str]:
    facts = []
    name = _resume_name(content)
    if name:
        facts.append(f"The user's name is {name}.")
    for email in _EMAIL_RE.findall(content)[:1]:
        facts.append(f"The user's email is {email}.")
    for phone in _PHONE_RE.findall(content)[:1]:
        facts.append(f"The user's phone number is {phone.strip()}.")
    inst = _institute(content)
    if inst:
        facts.append(f"The user studies at {inst}.")
    cgpa = _extract_cgpa(content)
    if cgpa:
        facts.append(f"The user's CGPA is {cgpa}.")
    return facts


_FACT_SYSTEM = (
    "You extract personal facts from a user's note. Reply ONLY with JSON: "
    '{"facts": ["...", "..."]}.\n'
    "Each fact must be a complete sentence about the user, phrased as "
    '"The user ...". Only facts stated in the note — never invent or infer '
    "beyond it. Skip trivial filler. 1-4 facts per note.\n"
    'Example: note "doctor appointment with Dr. Mehta on friday" -> '
    '{"facts": ["The user has a doctor appointment with Dr. Mehta on Friday."]}\n'
    'Example: note "i have to buy mangoes tomorrow" -> '
    '{"facts": ["The user needs to buy mangoes tomorrow."]}\n'
    'Example: note "remember to buy batteries for the remote" -> '
    '{"facts": ["The user needs to buy batteries for the remote."]}\n'
    'Example: note "my name is Dhruvil and I love running with my dog" -> '
    '{"facts": ["The user\'s name is Dhruvil.", "The user has a dog and loves running with it."]}'
)


def _client() -> ollama.Client:
    return ollama.Client(host=settings.ollama_host)


def note_facts(content: str) -> list[str]:
    """3b few-shot fact extraction for free-form notes (text/voice). Best-effort:
    any failure returns [] so ingestion never blocks on it."""
    if not content or not content.strip():
        return []
    try:
        response = _client().chat(
            model=settings.ollama_extract_model,
            messages=[
                {"role": "system", "content": _FACT_SYSTEM},
                {"role": "user", "content": content[:4000]},
            ],
            options={"temperature": 0.1, "think": False, "num_predict": 512},
        )
        raw = response["message"]["content"]
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return []
        data = json.loads(raw[start : end + 1])
        facts = []
        for f in data.get("facts", []):
            f = str(f).strip()
            if len(f) >= 8 and f.lower().startswith("the user"):
                facts.append(f)
        return facts
    except Exception:
        return []


def facts_for_capture(capture_type: str, content: str) -> list[str]:
    """Deterministic parsers where structure exists; 3b few-shot for free text.
    High-tier captures never reach this (sync_capture skips them entirely)."""
    if capture_type == "doc":
        if "TRANSCRIPT" in content.upper() or "GRADE" in content.upper():
            return transcript_facts(content)
        if "RESUME" in content.upper() or "EDUCATION" in content.upper():
            return resume_facts(content)
        return []
    return note_facts(content)