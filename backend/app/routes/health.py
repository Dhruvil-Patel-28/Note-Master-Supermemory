from fastapi import APIRouter

from .. import db
from ..config import settings

router = APIRouter(prefix="/health", tags=["health"])


def _vector_store_up() -> bool:
    if not settings.memory_enabled:
        return False
    try:
        from ..retrieval.vector_store import _get_collection

        _get_collection()
        return True
    except Exception:
        return False


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
    vector_store = "disabled" if not settings.memory_enabled else _vector_store_up()
    all_up = database and ollama_up and vector_store is True
    return {
        "status": "ok" if all_up else "degraded",
        "database": database,
        "ollama": ollama_up,
        "memory": vector_store,
    }