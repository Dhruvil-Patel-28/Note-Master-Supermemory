import os
import tempfile

import pytest

os.environ["NOTE_MASTER_DATA_DIR"] = tempfile.mkdtemp(prefix="note_master_test_")
os.environ["OCR_ENABLED"] = "0"
os.environ["MEMORY_ENABLED"] = "0"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    from app.db import get_conn

    return get_conn


@pytest.fixture(autouse=True)
def memory_hits(monkeypatch):
    """Route-level retrieval seam: the chat route reads supermemory, but tests
    must stay hermetic (no server, no real embeddings). Substitute a fake that
    returns every latest capture as a hit at 0.5 similarity (above the route's
    MIN_MEMORY_SIMILARITY floor) whenever the query shares a content word with
    at least one capture, and nothing otherwise — that mirrors the floor's
    honest-not-found behavior for out-of-vocabulary queries ("do i own a
    zebra" never drags the PAN note in). Semantic recall beyond lexical
    overlap is supermemory's job, covered by the @memory battery."""
    import re

    from app.db import get_conn
    from app.routes import chat as chat_route

    ACADEMIC = {
        "semester", "sem", "credit", "credits", "cgpa", "gpa", "grade",
        "course", "courses", "transcript", "marksheet",
    }

    def words(text: str) -> set[str]:
        out = set()
        for w in re.findall(r"[a-z]{3,}", text.lower()):
            stem = w.rstrip("es") if w.endswith("es") else w
            if stem.endswith("s"):
                stem = stem[:-1]
            out.add(stem)
        return out

    def fake(query: str) -> list[dict]:
        qwords = words(query)
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, content FROM captures WHERE is_latest = 1 ORDER BY id DESC LIMIT 5"
            ).fetchall()
        content_rows = [(r["id"], r["content"] or "") for r in rows]
        # Academic queries always match: transcripts label semesters with bare
        # digits/romans, so lexical overlap fails — supermemory's semantic
        # recall covers these in reality. Only the matched captures are
        # returned (real retrieval would rank them above unrelated notes; an
        # all-captures context makes the 3b answer from noise).
        matched = [r for r in content_rows if qwords & words(r[1])]
        if not matched and qwords & ACADEMIC:
            matched = content_rows
        hits = []
        for cid, content in matched:
            snippet = content.strip()
            if snippet:
                hits.append({"capture_id": cid, "snippet": snippet[:600], "similarity": 0.5})
        return hits

    monkeypatch.setattr(chat_route, "_memory_hits", fake)
    return fake