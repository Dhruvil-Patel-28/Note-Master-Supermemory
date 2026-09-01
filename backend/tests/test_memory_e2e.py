"""End-to-end battery against the LIVE local ChromaDB vector store (marker: memory).

These tests exercise the real knowledge layer on top of a real embedder:
captures index into ChromaDB via sync_capture, chat retrieves real vector hits.
They are NOT hermetic:

  - run ONLY via scripts/run-memory-tests.sh (sets MEMORY_ENABLED=1)
  - require Ollama on 127.0.0.1:11434 (nomic-embed-text + the chat model)
  - skip cleanly when the store/embedder is unreachable
  - run against the real persistent store (data/chromadb) — the tests are
    written so their assertions only need the documents they create and
    clean them up at the end
"""

import time

import pytest

pytestmark = pytest.mark.memory

_created: list[int] = []


@pytest.fixture(scope="module", autouse=True)
def _cleanup_created_captures():
    yield
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        for cid in _created:
            c.delete(f"/captures/{cid}")


def _wait_indexed(client, cap, timeout=180.0):
    """Wait for the capture's DB status == indexed (pipeline finished)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = client.get(f"/captures/{cap['id']}").json()
        if row["status"] == "indexed":
            return
        assert row["status"] != "failed", f"capture failed: {row.get('error')}"
        time.sleep(1)
    raise AssertionError(f"capture {cap['id']} not indexed within {timeout}s")


def _wait_searchable(cap, timeout=180.0):
    """Wait until the capture's chunks are searchable in ChromaDB (upsert is
    synchronous, so this is mostly a safety net). Query = the capture's own
    first chunk; same-embedding similarity ~1.0 so it must rank."""
    from app.embeddings.provider import embed
    from app.retrieval import vector_store as vs

    capture_id = cap["id"]
    query = (cap["content"] or "")[:200]
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            vec = embed([query])[0]
            results = vs.search(vec, k=50)
        except Exception:
            time.sleep(3)
            continue
        if any(str(r["capture_id"]) == str(capture_id) for r in results):
            return
        time.sleep(3)
    raise AssertionError(f"capture {capture_id} not searchable in memory within {timeout}s")


@pytest.fixture(scope="module")
def live_store():
    from app.config import settings
    from app.retrieval import vector_store as vs
    from app.embeddings.provider import embed

    if not settings.memory_enabled:
        pytest.skip("MEMORY_ENABLED != 1 — run via scripts/run-memory-tests.sh")
    try:
        embed(["probe"])
        vs.count()
    except Exception:
        pytest.skip("local ChromaDB/Ollama not reachable — launch Ollama + vector store")
    return vs


def _create_text(client, content):
    r = client.post("/captures/text", json={"content": content})
    assert r.status_code == 200, r.text
    cap = r.json()
    _created.append(cap["id"])
    _wait_indexed(client, cap)
    cap = client.get(f"/captures/{cap['id']}").json()
    _wait_searchable(cap)
    return cap


def test_semantic_recall_with_citation(client, live_store):
    cap = _create_text(client, "I study at the Indian Institute of Information Technology (IIIT), Nagpur")
    body = None
    for _ in range(3):
        r = client.post("/chat", json={"query": "where do i study"})
        assert r.status_code == 200, r.text
        body = r.json()
        if body["found"] and "IIIT" in body["answer"]:
            break
    assert body["found"], body
    assert "IIIT" in body["answer"]
    assert any(s["capture_id"] == cap["id"] for s in body["sources"])


def test_deterministic_transcript_facts_no_pin(client, live_store):
    transcript = (
        "TRANSCRIPT\n"
        "I\nMAL103 CALCULUS FOR ENGINEERS\nAB\n4\n"
        "Total\nII\nMAL 104 MATRICES\nCD\n4\n"
        "Total\nCGPA\n:\n7.57\nGrand\tTotal\tCredit\n:\n122"
    )
    _create_text(client, transcript)
    r = client.post("/chat", json={"query": "how many credits have i earned"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] and "122" in body["answer"]


def test_pan_query_answered_from_memory(client, live_store):
    cap = _create_text(client, "My PAN number is ABCDE1234F")
    body = None
    for _ in range(3):
        r = client.post("/chat", json={"query": "what is my pan number"})
        assert r.status_code == 200, r.text
        body = r.json()
        if body["found"] and "ABCDE1234F" in body["answer"]:
            break
    assert body["found"], body
    assert "ABCDE1234F" in body["answer"]
    assert any(s["capture_id"] == cap["id"] for s in body["sources"])

    # The PAN content sits in the local vector store (searching for its exact
    # text hits the capture).
    from app.embeddings.provider import embed
    from app.retrieval import vector_store as vs

    vec = embed(["ABCDE1234F"])[0]
    hits = vs.search(vec, k=50)
    assert any(str(r["capture_id"]) == str(cap["id"]) for r in hits)


def test_code_question_refused_cleanly(client, live_store):
    r = client.post("/chat", json={"query": "please print my name in python"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is False
    assert body["sources"] == []
    assert "print(" not in body["answer"]


def test_memory_down_degrades_to_honest_not_found(client, live_store, monkeypatch):
    from app.retrieval import context as ctx

    def boom(*a, **k):
        raise ConnectionError("memory down")

    monkeypatch.setattr(ctx, "_vector_hits", boom)
    r = client.post("/chat", json={"query": "do i own a zebra"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is False
    assert body["answer"] == "I don't have this in my notes."
    assert body["sources"] == []