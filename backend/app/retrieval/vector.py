from .. import db
from ..ingestion.embeddings import embed_texts


def search(query: str, limit: int = 10, include_old_versions: bool = False) -> list[dict]:
    embedding = embed_texts([query])[0]
    params: list = [str(embedding), limit]
    sql = """
        SELECT c.id AS capture_id, ch.text AS snippet, v.distance AS score
        FROM chunks_vec v
        JOIN capture_chunks ch ON ch.id = v.rowid
        JOIN captures c ON c.id = ch.capture_id
        WHERE v.embedding MATCH ? AND v.k = ?
    """
    if not include_old_versions:
        sql += " AND c.is_latest = 1"
    with db.get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]