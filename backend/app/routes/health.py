from fastapi import APIRouter

from .. import db
from ..config import settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health():
    database = True
    try:
        with db.get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        database = False
    try:
        import ollama

        ollama.Client(host=settings.ollama_host).list()
        ollama_up = True
    except Exception:
        ollama_up = False
    return {
        "status": "ok" if database and ollama_up else "degraded",
        "database": database,
        "ollama": ollama_up,
    }