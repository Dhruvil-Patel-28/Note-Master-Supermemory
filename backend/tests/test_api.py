import time

import pytest

llm = pytest.mark.llm


def create_text(client, content):
    r = client.post("/captures/text", json={"content": content})
    assert r.status_code == 200, r.text
    return wait_indexed(client, r.json())


def wait_indexed(client, cap, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/captures/{cap['id']}")
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] in ("indexed", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"capture {cap['id']} not indexed within {timeout}s")


def upload_file(client, path, filename=None, document_group_id=None):
    with open(path, "rb") as fh:
        r = client.post(
            "/captures/file",
            files={"file": (filename or path.name, fh, "application/octet-stream")},
            params={"document_group_id": document_group_id} if document_group_id else {},
        )
    assert r.status_code == 200, r.text
    return wait_indexed(client, r.json())


@llm
def test_create_and_index_text_capture(client):
    cap = create_text(client, "My PAN number is ABCDE1234F")
    assert cap["type"] == "text"
    assert cap["status"] == "indexed"
    assert cap["version_number"] == 1
    assert cap["document_group_id"] == cap["id"]


@llm
def test_versioned_reupload_flips_is_latest(client, tmp_path):
    p = tmp_path / "stmt.txt"
    p.write_text("Bank statement: balance 1000")
    v1 = upload_file(client, p)
    p.write_text("Bank statement: balance 2500")
    v2 = upload_file(client, p, document_group_id=v1["document_group_id"])
    assert v1["document_group_id"] == v2["document_group_id"]
    assert v2["version_number"] == 2
    assert v2["is_latest"] is True

    caps = client.get("/captures").json()
    latest = [c for c in caps if c["document_group_id"] == v1["document_group_id"]]
    assert len(latest) == 1 and latest[0]["id"] == v2["id"]

    history = client.get(f"/captures/history/{v1['document_group_id']}").json()
    assert len(history) == 2
    assert history[0]["version_number"] == 2


@llm
def test_default_search_excludes_old_versions(client, tmp_path):
    p = tmp_path / "reg.txt"
    p.write_text("car registration number is MH12AB1234")
    v1 = upload_file(client, p)
    p.write_text("car registration number is DL8CQ1111")
    v2 = upload_file(client, p, document_group_id=v1["document_group_id"])

    def hit_ids(query, include_history=False):
        r = client.post("/chat", json={"query": query, "include_history": include_history})
        assert r.status_code == 200, r.text
        return [s["capture_id"] for s in r.json()["sources"]]

    assert v1["id"] not in hit_ids("car registration")
    assert v2["id"] in hit_ids("car registration")
    assert v1["id"] in hit_ids("car registration", include_history=True)


@llm
def test_delete_capture_cascades_to_fts(client):
    cap = create_text(client, "electricity bill amount 3500 rupees")
    r = client.post("/chat", json={"query": "electricity bill"})
    assert any(s["capture_id"] == cap["id"] for s in r.json()["sources"])

    assert client.delete(f"/captures/{cap['id']}").status_code == 204
    assert client.get(f"/captures/{cap['id']}").status_code == 404

    r = client.post("/chat", json={"query": "electricity bill"})
    assert all(s["capture_id"] != cap["id"] for s in r.json()["sources"])


@llm
def test_edit_capture_reindexes(client):
    from app.retrieval.fts import search as fts_search

    cap = create_text(client, "meeting with Ravi about project alpha")
    client.patch(f"/captures/{cap['id']}", json={"content": "meeting with Priya about project beta"})
    wait_indexed(client, {"id": cap["id"]})
    assert any(h["capture_id"] == cap["id"] for h in fts_search("Priya"))
    assert all(h["capture_id"] != cap["id"] for h in fts_search("Ravi"))


@llm
def test_grounded_not_found(client):
    create_text(client, "My PAN number is ABCDE1234F")
    r = client.post("/chat", json={"query": "How much is 2+2?"})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert body["answer"] == "I don't have this in my notes."


@llm
def test_grounded_answer_with_citation(client):
    create_text(client, "My PAN number is ABCDE1234F")
    r = client.post("/chat", json={"query": "What is my PAN number?"})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert "ABCDE1234F" in body["answer"]
    assert body["sources"]


@llm
def test_structured_fields_answer(client):
    create_text(client, "My PAN number is ABCDE1234F issued in my name")
    body = None
    for _ in range(3):
        r = client.post("/chat", json={"query": "What is my PAN number?"})
        assert r.status_code == 200
        body = r.json()
        if body["structured"] and body["structured"]["kind"] == "fields":
            break
    assert body["structured"] is not None
    assert body["structured"]["kind"] == "fields"
    assert body["structured"]["fields"], "expected extracted fields"
    keys = [f["key"].lower() for f in body["structured"]["fields"]]
    assert any("pan" in k for k in keys)


@llm
def test_structured_prose_answer(client):
    create_text(client, "Goa trip was in December with friends")
    r = client.post("/chat", json={"query": "Where did I go in December?"})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["structured"]["kind"] in ("fields", "prose")


@llm
def test_vector_search_recall(client):
    create_text(client, "I love running along Marine Drive at sunrise")
    r = client.post("/chat", json={"query": "jogging near the sea in the morning"})
    assert r.status_code == 200
    assert any("Marine Drive" in s["snippet"] for s in r.json()["sources"])


@llm
def test_vector_search_excludes_old_versions(client, tmp_path):
    p = tmp_path / "plan.txt"
    p.write_text("road trip planned to the mountains this summer")
    v1 = upload_file(client, p)
    p.write_text("road trip planned to the beaches this summer")
    v2 = upload_file(client, p, document_group_id=v1["document_group_id"])
    r = client.post("/chat", json={"query": "summer vacation destination"})
    assert v1["id"] not in [s["capture_id"] for s in r.json()["sources"]]
    assert v2["id"] in [s["capture_id"] for s in r.json()["sources"]]


@llm
def test_delete_capture_cascades_chunks(client):
    from app.db import get_conn

    cap = create_text(client, "electricity bill amount 3500 rupees")
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM capture_chunks WHERE capture_id = ?", (cap["id"],)).fetchone()[0]
    assert n >= 1
    with get_conn() as conn:
        nv = conn.execute(
            "SELECT COUNT(*) FROM chunks_vec v JOIN capture_chunks ch ON ch.id = v.rowid WHERE ch.capture_id = ?",
            (cap["id"],),
        ).fetchone()[0]
    assert nv == n
    client.delete(f"/captures/{cap['id']}")
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM capture_chunks WHERE capture_id = ?", (cap["id"],)).fetchone()[0]
        nv = conn.execute(
            "SELECT COUNT(*) FROM chunks_vec v JOIN capture_chunks ch ON ch.id = v.rowid WHERE ch.capture_id = ?",
            (cap["id"],),
        ).fetchone()[0]
    assert n == 0 and nv == 0


@llm
def test_edit_reindexes_chunks(client):
    from app.db import get_conn

    cap = create_text(client, "meeting with Ravi about project alpha")
    with get_conn() as conn:
        old = conn.execute(
            "SELECT text FROM capture_chunks WHERE capture_id = ?", (cap["id"],)
        ).fetchone()["text"]
    client.patch(f"/captures/{cap['id']}", json={"content": "meeting with Priya about project beta"})
    wait_indexed(client, {"id": cap["id"]})
    with get_conn() as conn:
        new = conn.execute(
            "SELECT text FROM capture_chunks WHERE capture_id = ?", (cap["id"],)
        ).fetchone()["text"]
    assert old != new and "Priya" in new


@llm
def test_file_upload_docx(client, tmp_path):
    from docx import Document

    p = tmp_path / "note.docx"
    doc = Document()
    doc.add_paragraph("lease agreement signed with landlord")
    doc.save(p)
    cap = upload_file(client, p)
    assert cap["type"] == "doc"
    assert cap["status"] == "indexed"
    assert "lease agreement" in cap["content"]
    r = client.post("/chat", json={"query": "lease agreement"})
    assert any(s["capture_id"] == cap["id"] for s in r.json()["sources"])


def test_unsupported_file_rejected(client):
    r = client.post(
        "/captures/file", files={"file": ("evil.exe", b"MZ", "application/octet-stream")}
    )
    assert r.status_code == 422


def test_empty_text_rejected(client):
    assert client.post("/captures/text", json={"content": "   "}).status_code == 422


@llm
def test_entity_extraction_creates_graph(client):
    from app import graph

    cap = create_text(client, "My PAN number is ABCDE1234F issued by Income Tax Department")
    with graph.get_conn() as conn:
        rows = graph._rows(
            conn,
            "MATCH (c:Capture {id: $id})-[:MENTIONS]->(e:Entity) RETURN e.name AS name",
            {"id": cap["id"]},
        )
    assert "abcde1234f" in [r["name"] for r in rows]


@llm
def test_graph_two_hop_related_capture(client):
    from app import graph

    create_text(client, "The electricity bill was issued by Adani Power")
    cap2 = create_text(client, "Call Adani Power for outages, helpline 1800-233")
    ids = [h["capture_id"] for h in graph.search(["electricity bill"])]
    assert cap2["id"] in ids, f"expected 2-hop reach of {cap2['id']}, got {ids}"


@llm
def test_graph_versioning_excludes_old(client, tmp_path):
    from app import graph

    p = tmp_path / "stmt.txt"
    p.write_text("Bank statement for account ACC-777")
    v1 = upload_file(client, p)
    p.write_text("Bank statement for account ACC-888")
    v2 = upload_file(client, p, document_group_id=v1["document_group_id"])
    ids = [h["capture_id"] for h in graph.search(["bank statement"])]
    assert v2["id"] in ids
    assert v1["id"] not in ids


@llm
def test_edit_capture_reindexes_graph(client):
    from app import graph

    cap = create_text(client, "meeting with Ravi about project alpha")
    client.patch(f"/captures/{cap['id']}", json={"content": "meeting with Priya about project beta"})
    wait_indexed(client, {"id": cap["id"]})
    with graph.get_conn() as conn:
        rows = graph._rows(
            conn,
            "MATCH (c:Capture {id: $id})-[:MENTIONS]->(e:Entity) RETURN e.name AS name",
            {"id": cap["id"]},
        )
    names = [r["name"] for r in rows]
    assert "priya" in names
    assert "ravi" not in names