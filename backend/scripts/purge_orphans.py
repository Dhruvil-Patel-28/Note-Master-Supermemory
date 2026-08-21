"""Purge supermemory docs (and their graph memories) that no local capture owns.

Why this exists: forget_capture is best-effort — a delete during a slow memory
agent run (409 "still processing" for up to 90s) or a lost memory_doc_ids
column leaves orphaned documents behind, and retrieval keeps ranking them.
customIds are deterministic (nm-{capture_id}-{slot}), so ownership is
checkable against the local SQLite DB.

Usage (from backend/):
    uv run python scripts/purge_orphans.py            # dry run: list orphans
    uv run python scripts/purge_orphans.py --delete   # actually delete them
    uv run python scripts/purge_orphans.py --all      # treat every nm-* doc as
                                                      #   orphan (empty-DB reset)

After deleting docs, run scripts/clean_memories.py to sweep graph memories
left ungrounded by the removals.
"""

import argparse
import os
import re
import sqlite3
import sys

import httpx

KEY = os.environ.get("MEMORY_API_KEY") or (
    open(os.path.expanduser("~/.supermemory/api-key")).read().strip()
    if os.path.exists(os.path.expanduser("~/.supermemory/api-key"))
    else ""
)
BASE = os.environ.get("MEMORY_URL", "http://localhost:6767")
TAG = os.environ.get("MEMORY_CONTAINER_TAG", "user_main")
DATA_DIR = os.environ.get("NOTE_MASTER_DATA_DIR", "data")

_CUSTOM_ID_RE = re.compile(r"^nm-(\d+)-")


def owned_capture_ids() -> set[int]:
    db_path = os.path.join(DATA_DIR, "note_master.db")
    if not os.path.exists(db_path):
        return set()
    conn = sqlite3.connect(db_path)
    try:
        return {int(r[0]) for r in conn.execute("SELECT id FROM captures")}
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true", help="delete orphans (default: dry run)")
    parser.add_argument("--all", action="store_true", help="purge every nm-* doc regardless of DB state")
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {KEY}"} if KEY else {}
    owned = set() if args.all else owned_capture_ids()

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{BASE}/v3/documents/list",
            json={"containerTag": TAG, "limit": 1000},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        docs = data.get("memories") or data.get("documents") or []
        print(f"docs in store: {len(docs)}")

        orphans = []
        for d in docs:
            if args.all:
                orphans.append(d)
                continue
            custom_id = d.get("customId") or ""
            m = _CUSTOM_ID_RE.match(custom_id)
            if not m:
                print(f"  skip (no nm-* customId): {d['id']} {custom_id!r}")
                continue
            if int(m.group(1)) not in owned:
                orphans.append(d)

        if not orphans:
            print("no orphans — store is clean")
            return 0

        for d in orphans:
            label = d.get("customId") or d["id"]
            if not args.delete:
                print(f"  ORPHAN: {label} (capture {d.get('metadata', {}).get('capture_id')})")
                continue
            r = client.delete(f"{BASE}/v3/documents/{d['id']}", headers=headers)
            status = "deleted" if r.status_code < 300 else f"FAILED {r.status_code}: {r.text[:120]}"
            print(f"  {label}: {status}")

        if args.delete:
            after = client.post(
                f"{BASE}/v3/documents/list",
                json={"containerTag": TAG, "limit": 1000},
                headers=headers,
            ).json()
            remaining = after.get("memories") or after.get("documents") or []
            print(f"docs remaining: {len(remaining)}")
            print("next: uv run python scripts/clean_memories.py  # sweep ungrounded graph memories")
    return 0


if __name__ == "__main__":
    sys.exit(main())
