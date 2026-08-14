import json
import re

import ollama

from ..config import settings

ENTITY_TYPES = [
    "Person",
    "Account",
    "Organization",
    "Date",
    "Amount",
    "Location",
    "Topic",
]
RELATION_TYPES = ["ISSUED_BY", "BELONGS_TO", "RELATED_TO"]
GENERIC_NAMES = {
    "i", "me", "my", "mine", "we", "us", "our", "you", "your",
    "the", "a", "an", "it", "this", "that", "there", "here",
}


def _client() -> ollama.Client:
    return ollama.Client(host=settings.ollama_host)


def normalize(name: str) -> str:
    cleaned = re.sub(r"[\"'.!?;:,()]", "", name).strip()
    return " ".join(cleaned.lower().split())


def parse_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    data = json.loads(text)
    entities = []
    seen = set()
    for ent in data.get("entities", []):
        name = normalize(str(ent.get("name", "")))
        etype = str(ent.get("type", "Topic"))
        if not name or name in seen or name in GENERIC_NAMES:
            continue
        if etype not in ENTITY_TYPES:
            etype = "Topic"
        seen.add(name)
        entities.append({"name": name, "type": etype})
    names = {e["name"] for e in entities}
    relations = []
    for rel in data.get("relations", []):
        source = normalize(str(rel.get("from", "")))
        target = normalize(str(rel.get("to", "")))
        relation = str(rel.get("relation", "RELATED_TO")).upper()
        if not source or not target or source == target:
            continue
        if relation not in RELATION_TYPES:
            relation = "RELATED_TO"
        if source not in names or target not in names:
            continue
        relations.append({"from": source, "relation": relation, "to": target})
    return {"entities": entities, "relations": relations}


def extract(text: str) -> dict:
    prompt = (
        "You are an entity extraction assistant. Extract entities and relations from the note.\n"
        "Important: include important noun phrases and document names even if they seem generic "
        "(e.g. \"electricity bill\", \"bank statement\", \"car insurance\"). Only skip pronouns "
        "like \"i\" or \"me\".\n"
        "A relation is directed: {\"from\": X, \"relation\": R, \"to\": Y} means X is R by Y "
        "(e.g. bill ISSUED_BY company, account BELONGS_TO bank).\n"
        'Reply with JSON only, in exactly this shape:\n'
        '{"entities": [{"name": "...", "type": "Person|Account|Organization|Date|Amount|Location|Topic"}], '
        '"relations": [{"from": "...", "relation": "ISSUED_BY|BELONGS_TO|RELATED_TO", "to": "..."}]}\n'
        'Example: note "The electricity bill was issued by Adani Power for 3500 rupees" -> '
        '{"entities": [{"name": "electricity bill", "type": "Topic"}, {"name": "Adani Power", "type": "Organization"}, '
        '{"name": "3500 rupees", "type": "Amount"}], '
        '"relations": [{"from": "electricity bill", "relation": "ISSUED_BY", "to": "Adani Power"}]}\n'
        'Example: note "Bank statement for account ACC-777" -> '
        '{"entities": [{"name": "bank statement", "type": "Topic"}, {"name": "ACC-777", "type": "Account"}], '
        '"relations": [{"from": "bank statement", "relation": "BELONGS_TO", "to": "ACC-777"}]}\n\n'
        f"Note: {text}\n\nExtraction (JSON only):"
    )
    response = _client().chat(
        model=settings.ollama_extract_model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1, "think": False},
    )
    return parse_response(response["message"]["content"])