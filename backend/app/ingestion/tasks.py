from fastapi import BackgroundTasks

from .pipeline import run_pipeline
# SENSITIVE-FACTS (OPT2): dormant — uncomment with pipeline.py + routes/chat.py
# to restore the identity-fact extraction (scheduled on PATCH-to-high).
# from .sensitive import extract_sensitive_facts


def schedule_ingest(background: BackgroundTasks, capture_id: int) -> None:
    background.add_task(run_pipeline, capture_id)


# SENSITIVE-FACTS (OPT2): dormant — revive with the import above and
# routes/captures.py::patch_capture's schedule_sensitive_facts call.
# def schedule_sensitive_facts(background: BackgroundTasks, capture_id: int) -> None:
#     """(Re)extract identity facts for a capture that just became high-tier —
#     used by the PATCH re-classify path, where the content is already extracted
#     and only the labels changed (no full pipeline run needed)."""
#     background.add_task(_extract_facts_for, capture_id)
#
#
# def _extract_facts_for(capture_id: int) -> None:
#     import json
#
#     from .. import db
#
#     with db.get_conn() as conn:
#         row = conn.execute(
#             "SELECT content, sensitivity_tier FROM captures WHERE id = ?", (capture_id,)
#         ).fetchone()
#     if row is None:
#         return
#     facts = extract_sensitive_facts(row["content"] or "") if row["sensitivity_tier"] == "high" else {}
#     with db.get_conn() as conn:
#         conn.execute(
#             "UPDATE captures SET sensitive_facts = ? WHERE id = ?",
#             (json.dumps(facts), capture_id),
#         )