"""One-off: sweep duplicate and cross-attached memories from supermemory.

The memory agent (closed binary) builds its extraction context from the whole
space, and hermes3 mirrors that context into memories attributed to the wrong
doc (a one-line fact doc got 20 copies of the transcript's course memory).

Rules:
  1. Grounding: a memory is kept only if its text shares >=1 substantive token
     with the content of at least one of its attached docs (same spirit as the
     chat _grounded check). Cross-attached (contaminated) memories are deleted.
  2. Dedup: within the store, keep only the first memory per normalized text
     (whitespace + case folded). Identical copies are deleted.

Idempotent: re-running after the ingest queue drains sweeps the new junk too.
"""

import os
import re
import sys
from collections import Counter

import httpx

KEY = os.environ.get("MEMORY_API_KEY") or open(
    os.path.expanduser("~/.supermemory/api-key")
).read().strip()
BASE = os.environ.get("MEMORY_URL", "http://localhost:6767")
TAG = os.environ.get("MEMORY_CONTAINER_TAG", "user_main")

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "has", "have", "had", "of",
    "in", "on", "at", "to", "for", "with", "and", "or", "but", "not", "no",
    "user", "his", "her", "their", "its", "it", "this", "that", "these",
    "those", "as", "by", "from", "be", "been", "being", "do", "does", "did",
    "my", "your", "you", "he", "she", "they", "we", "i", "me", "am", "into",
    "out", "about", "than", "so", "if", "then", "also", "very", "just",
}


def content_words(text):
    return {
        w
        for w in re.findall(r"[a-z0-9]{2,}", (text or "").lower())
        if w not in STOPWORDS
    }


def main():
    with httpx.Client(timeout=60) as client:
        headers = {"Authorization": f"Bearer {KEY}"}

        docs_resp = client.post(
            f"{BASE}/v3/documents/list",
            json={"containerTag": TAG, "limit": 1000},
            headers=headers,
        )
        docs_resp.raise_for_status()
        docs = docs_resp.json()
        docs = docs.get("memories") or docs.get("documents") or []
        print(f"docs: {len(docs)}")

        def fetch_content(doc_id: str) -> str:
            if doc_id in docs_by_id:
                return docs_by_id[doc_id]
            resp = client.get(f"{BASE}/v3/documents/{doc_id}", headers=headers)
            if resp.status_code != 200:
                return ""
            return resp.json().get("content") or ""

        docs_by_id = {}
        for d in docs:
            docs_by_id[d["id"]] = fetch_content(d["id"])

        mems_resp = client.post(
            f"{BASE}/v4/memories/list",
            json={"containerTags": [TAG], "limit": 500},
            headers=headers,
        )
        mems_resp.raise_for_status()
        memories = (mems_resp.json().get("memoryEntries") or [])
        print(f"memories before: {len(memories)}")

        to_delete = []
        kept_texts = set()
        grounded = 0
        for m in memories:
            text = m.get("memory") or ""
            doc_ids = m.get("documentIds") or []
            doc_contents = [docs_by_id.get(i, "") for i in doc_ids]
            words = content_words(text)
            ok = any(words & content_words(c) for c in doc_contents if c.strip())
            if not ok:
                to_delete.append(m["id"])
                continue
            grounded += 1
            key = re.sub(r"\s+", " ", text.lower()).strip()
            if key in kept_texts:
                to_delete.append(m["id"])
                continue
            kept_texts.add(key)

        print(f"grounded+unique: {grounded}, deleting: {len(to_delete)}")
        if not to_delete:
            return

        deleted = 0
        for mid in to_delete:
            resp = client.request(
                "DELETE",
                f"{BASE}/v4/memories",
                json={"containerTag": TAG, "id": mid},
                headers=headers,
            )
            if resp.status_code == 200:
                deleted += 1
            else:
                print(f"  delete {mid} failed: {resp.status_code} {resp.text[:120]}")
        print(f"deleted: {deleted}")

        after = client.post(
            f"{BASE}/v4/memories/list",
            json={"containerTags": [TAG], "limit": 500},
            headers=headers,
        ).json().get("memoryEntries") or []
        print(f"memories after: {len(after)}")


if __name__ == "__main__":
    main()