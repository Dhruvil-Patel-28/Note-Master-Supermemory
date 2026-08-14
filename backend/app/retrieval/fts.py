import re

from .. import db

_SPECIAL = re.compile(r'[^\w\s]')


def search(query: str, limit: int = 10, include_old_versions: bool = False) -> list[dict]:
    terms = [t for t in _SPECIAL.sub(" ", query).split() if t]
    if not terms:
        return []

    def run(match_expr: str) -> list[dict]:
        sql = f"""
            SELECT c.id AS capture_id, snippet(captures_fts, 0, '<b>', '</b>', '…', 20) AS snippet,
                   bm25(captures_fts) AS score
            FROM captures_fts
            JOIN captures c ON c.id = captures_fts.rowid
            WHERE captures_fts MATCH ?
        """
        params: list = [match_expr]
        if not include_old_versions:
            sql += " AND c.is_latest = 1"
        sql += " ORDER BY score LIMIT ?"
        params.append(limit)
        try:
            with db.get_conn() as conn:
                return [dict(r) for r in conn.execute(sql, params).fetchall()]
        except Exception:
            return []

    hits = run(" AND ".join(f'"{t}"' for t in terms))
    if hits:
        return hits
    return run(" OR ".join(f'"{t}"' for t in terms))