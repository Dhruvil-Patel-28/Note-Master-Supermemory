import time

import pytest


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


def test_create_and_index_text_capture(client):
    cap = create_text(client, "My PAN number is ABCDE1234F")
    assert cap["type"] == "text"
    assert cap["status"] == "indexed"
    assert cap["version_number"] == 1
    assert cap["document_group_id"] == cap["id"]


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


def test_delete_capture_cascades_to_fts(client):
    cap = create_text(client, "electricity bill amount 3500 rupees")
    r = client.post("/chat", json={"query": "electricity bill"})
    assert any(s["capture_id"] == cap["id"] for s in r.json()["sources"])

    assert client.delete(f"/captures/{cap['id']}").status_code == 204
    assert client.get(f"/captures/{cap['id']}").status_code == 404

    r = client.post("/chat", json={"query": "electricity bill"})
    assert all(s["capture_id"] != cap["id"] for s in r.json()["sources"])


def test_edit_capture_reindexes(client):
    cap = create_text(client, "meeting with Ravi about project alpha")
    r = client.patch(f"/captures/{cap['id']}", json={"content": "meeting with Priya about project beta"})
    assert r.status_code == 200, r.text
    wait_indexed(client, r.json())
    r = client.post("/chat", json={"query": "Priya"})
    assert any(s["capture_id"] == cap["id"] for s in r.json()["sources"])
    r = client.post("/chat", json={"query": "Ravi"})
    assert all(s["capture_id"] != cap["id"] for s in r.json()["sources"])


def test_grounded_not_found(client):
    create_text(client, "My PAN number is ABCDE1234F")
    r = client.post("/chat", json={"query": "How much is 2+2?"})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert body["answer"] == "I don't have this in my notes."


def test_grounded_answer_with_citation(client):
    create_text(client, "My PAN number is ABCDE1234F")
    r = client.post("/chat", json={"query": "What is my PAN number?"})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert "ABCDE1234F" in body["answer"]
    assert body["sources"]


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