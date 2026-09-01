"""Purge ChromaDB chunks whose capture no longer exists in the local SQLite DB.

Why this exists: forget_capture is best-effort — a crash mid-sync (or a wiped
note_master.db) can leave orphaned chunks behind, and retrieval keeps ranking
them. ChromaDB stores capture_id in each chunk's metadata, so ownership is
checkable against the local DB.

Usage (from backend/):
    uv run python scripts/purge_orphans.py            # dry run: list orphans
    uv run python scripts/purge_orphans.py --delete   # actually delete them
    uv run python scripts/purge_orphans.py --all      # wipe the whole store
                                                      #   (empty-DB reset)

Needs MEMORY_ENABLED=1 and a reachable persist dir (CHROMA_PERSIST_DIR /
NOTE_MASTER_DATA_DIR).
"""

import argparse
import os
import sqlite3
import sys

import chromadb

DATA_DIR = os.environ.get("NOTE_MASTER_DATA_DIR", "data")
PERSIST_DIR = os.environ.get(
    "CHROMA_PERSIST_DIR", os.path.join(DATA_DIR, "chromadb")
)


def owned_capture_ids() -> set[int]:
    db_path = os.path.join(DATA_DIR, "note_master.db")
    if not os.path.exists(db_path):
        return set()
    conn = sqlite3.connect(db_path)
    try:
        return {int(r[0]) for r in conn.execute("SELECT id FROM captures")}
    finally:
        conn.close()


def _all_chunks() -> list[tuple[str, str]]:
    client = chromadb.PersistentClient(path=PERSIST_DIR)
    col = client.get_collection("note_master")
    if col.count() == 0:
        return []
    rows = col.get(include=["metadatas"])
    return list(zip(rows["ids"], rows["metadatas"] or []))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true", help="delete orphans (default: dry run)")
    parser.add_argument("--all", action="store_true", help="purge every chunk regardless of DB state")
    args = parser.parse_args()

    owned = set() if args.all else owned_capture_ids()

    chunks = _all_chunks()
    print(f"chunks in store: {len(chunks)}")

    orphans: list[tuple[str, str]] = []
    for chunk_id, meta in chunks:
        cid = (meta or {}).get("capture_id")
        if args.all or (cid is not None and int(cid) not in owned):
            orphans.append((chunk_id, cid))

    if not orphans:
        print("no orphans — store is clean")
        return 0

    for chunk_id, cid in orphans:
        if not args.delete:
            print(f"  ORPHAN: {chunk_id} (capture {cid})")

    if args.delete:
        col = None
        client = chromadb.PersistentClient(path=PERSIST_DIR)
        col = client.get_collection("note_master")
        col.delete(ids=[chunk_id for chunk_id, _ in orphans])
        print(f"deleted {len(orphans)} orphan chunks; remaining: {col.count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())