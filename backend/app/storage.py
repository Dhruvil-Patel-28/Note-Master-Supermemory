import shutil
import uuid
from pathlib import Path

from .config import settings


def save_upload(filename: str, data: bytes) -> str:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    rel = f"{uuid.uuid4().hex}{ext}"
    (settings.uploads_dir / rel).write_bytes(data)
    return rel


def resolve_path(rel: str) -> Path:
    return settings.uploads_dir / rel


def delete_file(rel: str) -> None:
    p = resolve_path(rel)
    if p.is_file():
        p.unlink()


def clear_uploads() -> None:
    shutil.rmtree(settings.uploads_dir, ignore_errors=True)