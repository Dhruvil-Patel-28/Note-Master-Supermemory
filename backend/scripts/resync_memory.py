"""Re-sync every latest capture into supermemory (re-runs the memory agent).

forget_capture (delete + poll + customId sweep) then sync_capture (re-add) —
the delete+re-add pattern that makes the memory agent re-run extraction with
the current provider (e.g. after switching SUPERMEMORY_PROVIDER to groq, or
after pipeline changes like raw-only sync).

Free-tier safe: --delay throttles captures so a bulk re-sync can't blow
through a daily token cap in one run. Upserts are idempotent
(nm-{capture_id}-raw customIds), so interrupting and re-running — even on a
later day after the quota resets — is always safe.

Run with MEMORY_ENABLED=1, MEMORY_API_KEY set, MEMORY_CONTAINER_TAG=user_main:
    uv run python scripts/resync_memory.py                 # default 5s delay
    uv run python scripts/resync_memory.py --delay 30      # gentler pace
    uv run python scripts/resync_memory.py --limit 20      # first 20 only
"""
import argparse
import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("resync")

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.memory.sync import forget_capture, sync_capture  # noqa: E402

assert settings.memory_enabled, "MEMORY_ENABLED not set"
assert settings.memory_container_tag == "user_main", "not pointed at user_main"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="seconds between captures (default 5) — keeps a bulk run inside "
        "free-tier token budgets; raise it for large documents",
    )
    parser.add_argument("--limit", type=int, default=0, help="only re-sync the first N captures (0 = all)")
    parser.add_argument("--id", type=int, default=0, help="re-sync a single capture by id (overrides --limit)")
    args = parser.parse_args()

    query = (
        "SELECT id, original_filename, note FROM captures "
        "WHERE is_latest = 1 AND memory_doc_ids IS NOT NULL AND memory_doc_ids != '' "
        "ORDER BY id"
    )
    params: tuple = ()
    if args.id:
        query += " AND id = ?"
        params = (args.id,)
    with db.get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    if not rows and args.id:
        # Capture exists but has no stored doc ids (interrupted first sync) —
        # still sync it so orphan sweeps / graph coverage can recover.
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT id, original_filename, note FROM captures WHERE is_latest = 1 AND id = ?",
                (args.id,),
            ).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    log.info("re-syncing %d captures into %s (delay %.0fs)", len(rows), settings.memory_container_tag, args.delay)
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
