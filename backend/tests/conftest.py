import os
import tempfile

import pytest

os.environ.setdefault("NOTE_MASTER_DATA_DIR", tempfile.mkdtemp(prefix="note_master_test_"))
os.environ.setdefault("OCR_ENABLED", "0")
# Docling loads layout models (~1GB) on first convert — far too heavy for the
# hermetic suite. Tests that exercise Docling enable it explicitly via
# object.__setattr__ on settings.
os.environ.setdefault("DOCLING_ENABLED", "0")
# The hermetic suite disables memory; the @memory run overrides this to "1"
# via scripts/run-memory-tests.sh. All test-process writes go to a dedicated
# container so the user's real data (user_main) is never touched.
os.environ.setdefault("MEMORY_ENABLED", "0")
os.environ.setdefault("MEMORY_CONTAINER_TAG", "nm_test")


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
def memory_hits(monkeypatch, request):
    """Route-level retrieval seam: the chat route reads supermemory, but tests
    must stay hermetic (no server, no real embeddings). Substitute a fake that
    returns only captures whose content shares a word with the query
    (plural-stemmed; academic queries — semester/credit/cgpa/grade/course/
    transcript — always match, transcripts label semesters with bare
    digits/romans so lexical overlap fails there), each at similarity 0.5; a
    query with no overlap ("do i own a zebra") returns nothing so the honest
    not-found path is exercised. Only matched captures are returned — an
    all-captures context made the 3b answer from noise.

    @memory and @retrieval tests bypass this fake entirely — they exercise the
    real _memory_hits against a live supermemory-server."""
    if request.node.get_closest_marker("memory") or request.node.get_closest_marker(
        "retrieval"
    ):
        return
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