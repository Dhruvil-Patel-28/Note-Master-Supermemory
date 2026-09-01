"""Pure-logic tests for ChromaDB sync (mock embed + vector store, no network)."""

from types import SimpleNamespace

from app import db
from app.db import init_db
from app.memory import sync as memsync

init_db()


class Recorder:
    def __init__(self):
        self.upserted = []  # (capture_id, n_chunks) in order
        self.deleted = []  # capture_ids deleted

    def upsert(self, capture_id, chunks, embeddings):
        self.upserted.append((capture_id, len(chunks)))
        return len(chunks)

    def delete_by_capture(self, capture_id):
        self.deleted.append(capture_id)
        return 1

    def count(self):
        return sum(n for _, n in self.upserted)


def _enable_memory(monkeypatch):
    monkeypatch.setattr(memsync, "settings", SimpleNamespace(memory_enabled=True))
    rec = Recorder()
    import app.retrieval.vector_store as vs

    monkeypatch.setattr(vs, "upsert", rec.upsert)
    monkeypatch.setattr(vs, "delete_by_capture", rec.delete_by_capture)
    monkeypatch.setattr(vs, "count", rec.count)

    import app.embeddings.provider as prov

    monkeypatch.setattr(
        prov, "embed", lambda chunks: [[0.0] * 768 for _ in chunks]
    )
    return rec


def _insert(content, note, group, latest=1, sensitivity="none"):
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO captures (type, content, note, sensitivity_tier, document_group_id, is_latest, version_number, status) "
            "VALUES ('text', ?, ?, ?, ?, ?, 1, 'indexed')",
            (content, note, sensitivity, group, latest),
        )
        cid = conn.execute(
            "SELECT id FROM captures WHERE document_group_id = ? AND is_latest = ?",
            (group, latest),
        ).fetchone()[0]
    return cid


def test_sync_writes_chunks(monkeypatch):
    rec = _enable_memory(monkeypatch)
    cid = _insert("i have to buy mangoes tomorrow", "grocery", 9999)
    memsync.sync_capture(cid)
    assert rec.upserted, "sync should upsert chunks"
    assert rec.upserted[0][0] == cid
    assert rec.upserted[0][1] >= 1


def test_sync_writes_high_tier_like_any_other(monkeypatch):
    rec = _enable_memory(monkeypatch)
    cid = _insert("PAN ABCDE1234F", "pan card", 8888, sensitivity="high")
    memsync.sync_capture(cid)
    assert rec.upserted and rec.upserted[0][0] == cid


def test_sync_forgets_demoted_siblings(monkeypatch):
    rec = _enable_memory(monkeypatch)
    old = _insert("old version", None, 7777, latest=0)
    new = _insert("new version", None, 7777, latest=1)
    memsync.sync_capture(new)
    assert old in rec.deleted


def test_forget_deletes_chunks(monkeypatch):
    rec = _enable_memory(monkeypatch)
    cid = _insert("some content", None, 6666)
    memsync.forget_capture(cid)
    assert cid in rec.deleted


def test_sync_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(memsync, "settings", SimpleNamespace(memory_enabled=False))
    rec = Recorder()
    import app.retrieval.vector_store as vs

    monkeypatch.setattr(vs, "upsert", rec.upsert)
    monkeypatch.setattr(vs, "delete_by_capture", rec.delete_by_capture)
    monkeypatch.setattr(vs, "count", rec.count)
    cid = _insert("content", None, 5555)
    memsync.sync_capture(cid)
    assert rec.upserted == []
    assert rec.deleted == []