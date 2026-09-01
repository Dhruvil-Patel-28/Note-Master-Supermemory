"""Re-index every latest capture into the local ChromaDB vector store.

forget_capture (delete) then sync_capture (re-add) — the delete+re-add pattern
that rebuilds a capture's chunks from scratch (e.g. after chunker/embedding/
filter changes, or after manually wiping the persist dir). Idempotent: chunk
ids are deterministic (nm-{capture_id}-chunk-{i}), so re-running is safe.

--delay throttles a bulk run so a slow machine (or an overloaded local
embedder) doesn't collapse — pure pacing, no quota concerns.

Run with MEMORY_ENABLED=1:
    uv run python scripts/resync_memory.py                 # default 5s delay
    uv run python scripts/resync_memory.py --delay 0       # full speed
    uv run python scripts/resync_memory.py --limit 20      # first 20 only
"""
import argparse
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("resync")

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.memory.sync import forget_capture, sync_capture  # noqa: E402

assert settings.memory_enabled, "MEMORY_ENABLED not set"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="seconds between captures (default 5) — more than enough for local "
        "embedding; raise it for very large documents",
    )
    parser.add_argument("--limit", type=int, default=0, help="only re-sync the first N captures (0 = all)")
    parser.add_argument("--id", type=int, default=0, help="re-sync a single capture by id (overrides --limit)")
    args = parser.parse_args()

    query = "SELECT id, original_filename, note FROM captures WHERE is_latest = 1 ORDER BY id"
    params: tuple = ()
    if args.id:
        query += " AND id = ?"
        params = (args.id,)
    with db.get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    log.info("re-syncing %d captures into ChromaDB (delay %.0fs)", len(rows), args.delay)
    t0 = time.time()
    failed = 0
    for i, row in enumerate(rows, 1):
        cid = row["id"]
        label = row["note"] or row["original_filename"] or ""
        try:
            forget_capture(cid)
            sync_capture(cid)
            log.info("[%d/%d] capture %d (%s) OK", i, len(rows), cid, label[:40])
        except Exception as exc:
            failed += 1
            log.error("[%d/%d] capture %d (%s) FAILED: %s", i, len(rows), cid, label[:40], exc)
        if i < len(rows) and args.delay > 0:
            time.sleep(args.delay)
    log.info("done in %.0fs (%d failed)", time.time() - t0, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())