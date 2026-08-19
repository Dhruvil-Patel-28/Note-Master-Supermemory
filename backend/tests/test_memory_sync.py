"""Pure-logic tests for memory sync (mock client, no network)."""

from types import SimpleNamespace

from app import db
from app.db import init_db
from app.memory import sync as memsync

init_db()


class FakeClient:
    def __init__(self):
        self.docs = {}
        self.deleted = []

    def add_document(self, content, container_tag=None, metadata=None, custom_id=None):
        doc_id = f"doc-{len(self.docs) + 1}"
        self.docs[doc_id] = {"content": content, "metadata": metadata or {}, "custom_id": custom_id}
        return doc_id

    def delete_document(self, doc_id):
        self.deleted.append(doc_id)
        self.docs.pop(doc_id, None)
        return True

    def document_status(self, doc_id):
        return "done" if doc_id in self.docs else None


def _enable_memory(monkeypatch):
    monkeypatch.setattr(
        memsync, "settings", SimpleNamespace(memory_enabled=True, memory_container_tag="user_main")
    )
    monkeypatch.setattr(memsync, "facts_for_capture", lambda type_, content: ["The user needs to buy mangoes tomorrow."])
    client = FakeClient()
    monkeypatch.setattr(memsync, "get_client", lambda: client)
    return client


def test_sync_writes_raw_and_fact_docs(monkeypatch):
    client = _enable_memory(monkeypatch)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO captures (type, content, note, sensitivity_tier, document_group_id, is_latest, version_number, status) "
            "VALUES ('text', 'i have to buy mangoes tomorrow', 'grocery', 'none', 9999, 1, 1, 'indexed')"
        )
        cid = conn.execute("SELECT id FROM captures WHERE document_group_id = 9999").fetchone()[0]
    memsync.sync_capture(cid)
    with db.get_conn() as conn:
        row = conn.execute("SELECT memory_doc_ids FROM captures WHERE id = ?", (cid,)).fetchone()
    assert row["memory_doc_ids"]
    ids = row["memory_doc_ids"].split(",")
    assert len(ids) == 2
    kinds = {client.docs[i]["metadata"]["kind"] for i in ids}
    assert kinds == {"raw", "fact"}
    raw_id = next(i for i in ids if client.docs[i]["metadata"]["kind"] == "raw")
    assert client.docs[raw_id]["custom_id"] == f"nm-{cid}-raw"
    assert client.docs[raw_id]["content"] == "grocery\ni have to buy mangoes tomorrow"


def test_sync_writes_high_tier_like_any_other(monkeypatch):
    client = _enable_memory(monkeypatch)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO captures (type, content, note, sensitivity_tier, document_group_id, is_latest, version_number, status) "
            "VALUES ('text', 'PAN ABCDE1234F', 'pan card', 'high', 8888, 1, 1, 'indexed')"
        )
        cid = conn.execute("SELECT id FROM captures WHERE document_group_id = 8888").fetchone()[0]
    memsync.sync_capture(cid)
    with db.get_conn() as conn:
        row = conn.execute("SELECT memory_doc_ids FROM captures WHERE id = ?", (cid,)).fetchone()
    assert row["memory_doc_ids"] is not None
    ids = row["memory_doc_ids"].split(",")
    assert len(ids) == 2
    kinds = {client.docs[i]["metadata"]["kind"] for i in ids}
    assert kinds == {"raw", "fact"}
    raw_id = next(i for i in ids if client.docs[i]["metadata"]["kind"] == "raw")
    assert client.docs[raw_id]["content"] == "pan card\nPAN ABCDE1234F"


def test_sync_forgets_demoted_siblings(monkeypatch):
    client = _enable_memory(monkeypatch)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO captures (type, content, note, sensitivity_tier, document_group_id, is_latest, version_number, status) "
            "VALUES ('text', 'old version', NULL, 'none', 7777, 0, 1, 'indexed')"
        )
        old = conn.execute("SELECT id FROM captures WHERE document_group_id = 7777").fetchone()[0]
        conn.execute(
            "INSERT INTO captures (type, content, note, sensitivity_tier, document_group_id, is_latest, version_number, status) "
            "VALUES ('text', 'new version', NULL, 'none', 7777, 1, 2, 'indexed')"
        )
        new = conn.execute("SELECT id FROM captures WHERE document_group_id = 7777 AND is_latest = 1").fetchone()[0]
        conn.execute("UPDATE captures SET memory_doc_ids = 'old-a,old-b' WHERE id = ?", (old,))
    memsync.sync_capture(new)
    assert set(client.deleted) == {"old-a", "old-b"}
    with db.get_conn() as conn:
        old_ids = conn.execute("SELECT memory_doc_ids FROM captures WHERE id = ?", (old,)).fetchone()[0]
    assert old_ids is None


def test_forget_deletes_stored_docs(monkeypatch):
    client = _enable_memory(monkeypatch)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO captures (type, content, note, sensitivity_tier, document_group_id, is_latest, version_number, status) "
            "VALUES ('text', 'some content', NULL, 'none', 6666, 1, 1, 'indexed')"
        )
        cid = conn.execute("SELECT id FROM captures WHERE document_group_id = 6666").fetchone()[0]
        conn.execute("UPDATE captures SET memory_doc_ids = 'a1,b2' WHERE id = ?", (cid,))
    memsync.forget_capture(cid)
    assert set(client.deleted) == {"a1", "b2"}
    with db.get_conn() as conn:
        ids = conn.execute("SELECT memory_doc_ids FROM captures WHERE id = ?", (cid,)).fetchone()[0]
    assert ids is None


def test_sync_is_noop_when_disabled():
    assert memsync.settings.memory_enabled is False
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO captures (type, content, note, sensitivity_tier, document_group_id, is_latest, version_number, status) "
            "VALUES ('text', 'content', NULL, 'none', 5555, 1, 1, 'indexed')"
        )
        cid = conn.execute("SELECT id FROM captures WHERE document_group_id = 5555").fetchone()[0]
    memsync.sync_capture(cid)
    with db.get_conn() as conn:
        row = conn.execute("SELECT memory_doc_ids FROM captures WHERE id = ?", (cid,)).fetchone()
    assert row["memory_doc_ids"] is None