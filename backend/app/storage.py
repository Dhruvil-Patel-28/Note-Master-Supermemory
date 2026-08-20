import shutil
import uuid
from pathlib import Path

from .config import settings


def save_upload(filename: str, src) -> str:
    """Stream an upload (bytes or file-like) to disk in chunks — big docs
    must never be read into RAM whole (a 100MB upload would OOM)."""
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    rel = f"{uuid.uuid4().hex}{ext}"
    target = settings.uploads_dir / rel
    with open(target, "wb") as out:
        if isinstance(src, bytes):
            out.write(src)
        else:
            shutil.copyfileobj(src, out)
    return rel


def resolve_path(rel: str) -> Path:
    return settings.uploads_dir / rel


def delete_file(rel: str) -> None:
    p = resolve_path(rel)
    if p.is_file():
        p.unlink()


def clear_uploads() -> None:
    shutil.rmtree(settings.uploads_dir, ignore_errors=True)