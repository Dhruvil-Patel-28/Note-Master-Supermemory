import re

from .. import db

_SPECIAL = re.compile(r'[^\w\s]')
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "he", "i", "in", "is", "it", "its", "me", "much", "my", "of", "on",
    "or", "that", "the", "this", "to", "was", "we", "were", "what", "will",
    "with", "you", "your",
    "about", "any", "can", "could", "did", "do", "does", "get", "going",
    "here", "how", "just", "know", "like", "please", "say", "said", "should",
    "show", "tell", "there", "want", "when", "where", "which", "who", "why",
    "would",
}


def _term_count(conn, term: str, include_old_versions: bool) -> int:
    sql = "SELECT COUNT(*) AS n FROM captures_fts"
    if not include_old_versions:
        sql += " JOIN captures c ON c.id = captures_fts.rowid WHERE c.is_latest = 1"
    else:
        sql += " WHERE 1=1"
    row = conn.execute(sql + " AND captures_fts MATCH ?", [f'"{term}"']).fetchone()
    return row["n"]


def _edit_variants(term: str):
    for i in range(len(term) + 1):
        yield term[:i] + term[i + 1:]
    for i in range(len(term)):
        for ch in "abcdefghijklmnopqrstuvwxyz":
            yield term[:i] + ch + term[i + 1:]
    for i in range(len(term) + 1):
        for ch in "abcdefghijklmnopqrstuvwxyz":
            yield term[:i] + ch + term[i:]


def _correct_terms(conn, terms: list[str], include_old_versions: bool) -> dict[str, list[str]]:
    """Find edit-distance-1 variants of each term that also match the index.

    A note saying "i have to but mangoes" is found by the query term "buy"
    through its variant "but". Variants matching the same documents as the
    term itself add nothing and are skipped.
    """
    corrections: dict[str, list[str]] = {}
    for t in terms:
        base = _term_count(conn, t, include_old_versions)
        found: list[str] = []
        for v in _edit_variants(t):
            if not v or len(v) < 2 or v in terms or v.lower() in _STOPWORDS:
                continue
            n = _term_count(conn, v, include_old_versions)
            if n > 0 and n >= base:
                found.append(v)
        if found:
            corrections[t] = found[:3]
    return corrections


def search(query: str, limit: int = 10, include_old_versions: bool = False) -> list[dict]:
    terms = [
        t
        for t in _SPECIAL.sub(" ", query).split()
        if t and len(t) >= 2 and t.lower() not in _STOPWORDS
    ]
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
    with db.get_conn() as conn:
        corrections = _correct_terms(conn, terms, include_old_versions)
    if not corrections:
        return run(" OR ".join(f'"{t}"' for t in terms))
    boosted = []
    for t in terms:
        expr = f'"{t}"'
        for v in corrections.get(t, [])[:3]:
            expr += f' OR "{v}"'
        boosted.append(f"({expr})")
    return run(" OR ".join(boosted))