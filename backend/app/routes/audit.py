from fastapi import APIRouter, Query

from .. import db
from ..schemas import AuditEntry

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditEntry])
def list_audit(limit: int = Query(100, ge=1, le=500)):
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, query, retrieved_source_ids, sensitive_access, created_at "
            "FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        AuditEntry(
            id=r["id"],
            query=r["query"],
            retrieved_source_ids=r["retrieved_source_ids"],
            sensitive_access=bool(r["sensitive_access"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]