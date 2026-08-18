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


def term_count(conn, term: str, include_old_versions: bool) -> int:
    """Number of captures whose FTS index contains `term` — used to validate
    typo variants and LLM-generated expansion anchors against the real index."""
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
        # Terms with digits ("2nd") are rarely typos of content words — their
        # variants ("end") can be real words elsewhere ("end-to-end" in a
        # resume) and flood the ranking.
        if re.search(r"\d", t):
            continue
        base = term_count(conn, t, include_old_versions)
        found: list[str] = []
        for v in _edit_variants(t):
            if not v or len(v) < 2 or v in terms or v.lower() in _STOPWORDS:
                continue
            n = term_count(conn, v, include_old_versions)
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

    def run(match_expr: str, limit: int, reorder: bool = False) -> list[dict]:
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
        params.append(limit * 3 if reorder else limit)
        try:
            with db.get_conn() as conn:
                rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        except Exception:
            return []
        if reorder:
            # bm25 favors short docs, so a single generic term ("name") can
            # outrank a doc matching several query terms — and drag a
            # sensitive capture into the PIN gate. Prefer rows that match
            # more distinct query terms, then bm25.
            rows.sort(key=lambda r: (-r["snippet"].count("<b>"), r["score"]))
            return rows[:limit]
        return rows

    hits = run(" AND ".join(f'"{t}"' for t in terms), limit)
    if hits:
        return hits
    with db.get_conn() as conn:
        corrections = _correct_terms(conn, terms, include_old_versions)
    if not corrections:
        return run(" OR ".join(f'"{t}"' for t in terms), limit, reorder=len(terms) > 1)
    boosted = []
    for t in terms:
        expr = f'"{t}"'
        for v in corrections.get(t, [])[:3]:
            expr += f' OR "{v}"'
        boosted.append(f"({expr})")
    return run(" OR ".join(boosted), limit, reorder=len(terms) > 1)