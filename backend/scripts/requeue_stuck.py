"""Recover captures stuck in queued/processing (server died or reloaded
mid-extraction). Flips them back to queued and re-runs the pipeline.

Large/page-heavy documents extract in an isolated subprocess with a hard
timeout, so a pathological file can no longer wedge the server or strand
itself permanently.

Usage (from backend/):
    MEMORY_ENABLED=1 uv run python scripts/requeue_stuck.py            # all stuck
    uv run python scripts/requeue_stuck.py --id 100                    # one capture
"""
import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("requeue")

from app import db  # noqa: E402
from app.ingestion.pipeline import run_pipeline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, help="recover a single capture id")
    args = parser.parse_args()

    with db.get_conn() as conn:
        if args.id:
            rows = conn.execute("SELECT id FROM captures WHERE id = ?", (args.id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM captures WHERE status IN ('queued', 'processing') ORDER BY id"
            ).fetchall()
        ids = [r["id"] for r in rows]
        if not ids:
            log.info("nothing stuck — clean")
            return 0
        conn.execute(
            f"UPDATE captures SET status = 'queued', error = NULL WHERE id IN ({','.join('?' for _ in ids)})",
            ids,
        )
    log.info("re-queuing %d capture(s): %s", len(ids), ids)

    failed = []
    for cid in ids:
        try:
            log.info("[%d] pipeline start", cid)
            run_pipeline(cid)
            log.info("[%d] done", cid)
        except Exception as exc:
            failed.append(cid)
            log.error("[%d] FAILED: %s", cid, str(exc)[:300])
    if failed:
        log.info("failed captures (status=failed with error): %s", failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
