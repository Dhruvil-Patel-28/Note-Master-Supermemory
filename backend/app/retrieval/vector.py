import array
import math

from .. import db
from ..ingestion.embeddings import embed_texts

MIN_COSINE_DISTANCE = 0.5


def _cosine_distance(query: list[float], vec: bytes) -> float:
    v = array.array("f", vec)
    dot = sum(a * b for a, b in zip(query, v))
    norm_q = math.sqrt(sum(a * a for a in query))
    norm_v = math.sqrt(sum(b * b for b in v))
    if norm_q == 0 or norm_v == 0:
        return 1.0
    return 1 - dot / (norm_q * norm_v)


def search(query: str, limit: int = 10, include_old_versions: bool = False) -> list[dict]:
    query_vec = embed_texts([query])[0]
    params: list = [str(query_vec), 12]
    sql = """
        SELECT c.id AS capture_id, ch.text AS snippet, ch.embedding AS embedding
        FROM chunks_vec v
        JOIN capture_chunks ch ON ch.id = v.rowid
        JOIN captures c ON c.id = ch.capture_id
        WHERE v.embedding MATCH ? AND v.k = ?
    """
    if not include_old_versions:
        sql += " AND c.is_latest = 1"
    with db.get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    hits = []
    for r in rows:
        row = dict(r)
        dist = _cosine_distance(query_vec, row["embedding"])
        if dist > MIN_COSINE_DISTANCE:
            continue
        row["distance"] = dist
        hits.append(row)
    hits.sort(key=lambda h: h["distance"])
    return hits[:limit]
