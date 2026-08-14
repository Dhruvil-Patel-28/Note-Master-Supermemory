from fastapi import BackgroundTasks

from .pipeline import run_pipeline


def schedule_ingest(background: BackgroundTasks, capture_id: int) -> None:
    background.add_task(run_pipeline, capture_id)