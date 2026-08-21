"""End-to-end battery against a LIVE local supermemory-server (marker: memory).

These tests exercise the real knowledge layer: captures mirror into
supermemory via sync_capture, chat retrieves over the real /v4/search, and
high-tier captures sync like any other. They are NOT hermetic:

  - run ONLY via scripts/run-memory-tests.sh (sets MEMORY_ENABLED=1,
    MEMORY_API_KEY from ~/.supermemory/api-key, MEMORY_CONTAINER_TAG=nm_test)
  - require the supermemory-server on 127.0.0.1:6767 (launched via
    scripts/run-supermemory.sh) and Ollama with the configured models
  - skip cleanly when the server is unreachable
  - write only into the nm_test container — the user's real data lives in
    user_main and is never touched; tests delete their captures at the end

Ingest is async (queued -> indexing -> done; the memory agent's runtime
depends on the configured provider — seconds on Groq, ~13-27s/doc with the
local 3b), so every test polls supermemory until its capture is searchable
(180s cap) before asserting on chat answers.
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
    """Wait until the capture's docs are searchable in supermemory (the memory
    agent must finish before /v4/search sees the new doc). The query is the
    capture's own content (search matches text, not customIds); with threshold
    0 the doc ranks among the results once done."""
    from app.memory.client import get_client

    capture_id = cap["id"]
    query = (cap["content"] or "")[:80]
    deadline = time.time() + timeout
    while time.time() < deadline:
        results = get_client().search(query, limit=10)
        if any(str(r["metadata"].get("capture_id")) == str(capture_id) for r in results):
            return
        time.sleep(3)
    raise AssertionError(f"capture {capture_id} not searchable in memory within {timeout}s")


@pytest.fixture(scope="module")
def live_memory():
    from app.config import settings
    from app.memory.client import get_client

    if not settings.memory_enabled:
        pytest.skip("MEMORY_ENABLED != 1 — run via scripts/run-memory-tests.sh")
    if not get_client().healthy():
        pytest.skip("supermemory-server not reachable on 127.0.0.1:6767 — launch via scripts/run-supermemory.sh")
    return get_client()


def _create_text(client, content):
    r = client.post("/captures/text", json={"content": content})
    assert r.status_code == 200, r.text
    cap = r.json()
    _created.append(cap["id"])
    _wait_indexed(client, cap)
    # The POST response serializes the row BEFORE the pipeline's background
    # task runs — sensitivity_tier there is stale ("" for new captures). Re-fetch
    # so the high-tier shortcut in _wait_searchable sees the real tier.
    cap = client.get(f"/captures/{cap['id']}").json()
    _wait_searchable(cap)
    return cap


def test_semantic_recall_with_citation(client, live_memory):
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


def test_deterministic_transcript_facts_no_pin(client, live_memory):
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


def test_pan_query_answered_from_memory(client, live_memory):
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

    # High-tier captures sync like any other — the PAN content is in the
    # knowledge store (searching for its exact content hits the capture).
    hits = live_memory.search("ABCDE1234F")
    assert any(str(h["metadata"].get("capture_id")) == str(cap["id"]) for h in hits)


def test_code_question_refused_cleanly(client, live_memory):
    r = client.post("/chat", json={"query": "please print my name in python"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is False
    assert body["sources"] == []
    assert "print(" not in body["answer"]


def test_memory_down_degrades_to_honest_not_found(client, live_memory, monkeypatch):
    from app.routes import chat as chat_route

    def boom(*a, **k):
        raise ConnectionError("memory down")

    monkeypatch.setattr(chat_route, "get_client", boom)
    r = client.post("/chat", json={"query": "do i own a zebra"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is False
    assert body["answer"] == "I don't have this in my notes."
    assert body["sources"] == []