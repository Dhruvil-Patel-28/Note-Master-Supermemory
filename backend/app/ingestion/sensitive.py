"""Structured facts for high-tier (sensitive) captures — extracted ONCE at
ingest from the extracted text with the local 3b model, stored locally in
`captures.sensitive_facts` (never mirrored to supermemory, by design: the
knowledge layer must not hold PAN/Aadhaar-adjacent data).

DORMANT (OPT2): nothing imports this module since identity moved to
supermemory retrieval. Revive together with the SENSITIVE-FACTS blocks in
tasks.py and routes/chat.py.

The extraction is best-effort: any failure yields an empty dict (ingestion
never fails because of it).
"""

import json
import logging
import re

from ..config import settings
from ..retrieval.chat import _client

logger = logging.getLogger(__name__)

FACT_KEYS = ("name", "address", "date_of_birth", "id_number", "phone")

_SYSTEM = (
    "You extract identity fields from a document's extracted text. Reply ONLY with JSON: "
    '{"name": "<full name>", "address": "<address>", "date_of_birth": "<DOB>", '
    '"id_number": "<document/ID number>", "phone": "<phone number>"}.\n'
    "Rules: use an empty string for any field NOT present in the text — never invent values. "
    "If the text is garbled OCR, use what is legible. id_number is a 12-digit Aadhaar, PAN, "
    "passport or account number exactly as printed. date_of_birth as printed (e.g. DD/MM/YYYY).\n"
    'Example: Document: "Government of India Aadhaar Card Name: Rahul Sharma DOB: 15/08/1996 '
    'Aadhaar Number: 1234 5678 9012 Address: 21 MG Road, Pune" '
    'Answer: {"name": "Rahul Sharma", "address": "21 MG Road, Pune", "date_of_birth": "15/08/1996", '
    '"id_number": "1234 5678 9012", "phone": ""}\n'
    'Example: Document: "Income Tax Department PAN Card XYZPS1234F Sonal Mehta" '
    'Answer: {"name": "Sonal Mehta", "address": "", "date_of_birth": "", '
    '"id_number": "XYZPS1234F", "phone": ""}'
)


def _parse_facts(raw: str) -> dict[str, str]:
    try:
        payload = json.loads(raw)
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            payload = json.loads(raw[start : end + 1])
        except Exception:
            return {}
    if not isinstance(payload, dict):
        return {}
    facts: dict[str, str] = {key: "" for key in FACT_KEYS}
    for key in FACT_KEYS:
        value = payload.get(key)
        if isinstance(value, str):
            value = re.sub(r"\s+", " ", value.strip())
            facts[key] = value[:300]
    return facts


def extract_sensitive_facts(content: str) -> dict[str, str]:
    """One local 3b call; never raises — ingestion must not fail on facts."""
    if not (content or "").strip():
        return {}
    try:
        response = _client().chat(
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": content[:6000]},
            ],
            options={"temperature": 0.1, "think": False, "num_predict": 512},
        )
        return _parse_facts(response["message"]["content"])
    except Exception as exc:
        logger.warning("sensitive facts extraction failed: %s", exc)
        return {}