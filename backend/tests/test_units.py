import pytest

from app import graph
from app.config import settings
from app.guardrails import pin
from app.ingestion.chunker import chunk_text
from app.ingestion.classify import classify
from app.ingestion.extract import parse_response
from app.retrieval.fusion import fuse


class TestChunker:
    def test_empty_text(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text(self):
        assert chunk_text("hello world") == ["hello world"]

    def test_long_text_splits_and_overlaps(self):
        text = "word " * 300
        chunks = chunk_text(text)
        assert len(chunks) > 1
        assert all(len(c) <= 800 for c in chunks)
        assert chunks[0][-100:] in chunks[1]


class TestFusion:
    def test_three_way_dedupes_by_capture(self):
        fts = [{"capture_id": 1, "snippet": "a"}, {"capture_id": 2, "snippet": "b"}]
        vec = [{"capture_id": 2, "snippet": "b"}, {"capture_id": 3, "snippet": "c"}]
        gph = [{"capture_id": 3, "snippet": "c"}, {"capture_id": 4, "snippet": "d"}]
        out = fuse(fts, vec, gph, limit=10)
        assert [h["capture_id"] for h in out] == [2, 3, 1, 4]

    def test_fts_only_when_others_empty(self):
        fts = [{"capture_id": 1, "snippet": "a"}]
        assert fuse(fts, [], []) == fts

    def test_limit(self):
        fts = [{"capture_id": i, "snippet": str(i)} for i in range(1, 8)]
        out = fuse(fts, [], [], limit=3)
        assert len(out) == 3


class TestExtractParse:
    def test_plain_json(self):
        raw = '{"entities": [{"name": "Adani Power", "type": "Organization"}, {"name": "3500 rupees", "type": "Amount"}], "relations": []}'
        data = parse_response(raw)
        assert data["entities"][0]["name"] == "adani power"
        assert data["entities"][0]["type"] == "Organization"
        assert data["entities"][1]["type"] == "Amount"

    def test_fenced_json(self):
        raw = '```json\n{"entities": [{"name": "Ravi", "type": "Person"}], "relations": []}\n```'
        assert parse_response(raw)["entities"][0]["name"] == "ravi"

    def test_filters_bad_entities_and_relations(self):
        raw = (
            '{"entities": [{"name": "  Alice  ", "type": "Person"}, {"name": "me", "type": "Topic"}, '
            '{"name": "Bob", "type": "Unknown"}], "relations": ['
            '{"from": "Alice", "relation": "KNOWS", "to": "Bob"}, '
            '{"from": "Alice", "relation": "RELATED_TO", "to": "Carol"}]}'
        )
        data = parse_response(raw)
        names = [e["name"] for e in data["entities"]]
        assert names == ["alice", "bob"]
        assert data["entities"][1]["type"] == "Topic"
        assert len(data["relations"]) == 1
        assert data["relations"][0]["relation"] == "RELATED_TO"
        assert data["relations"][0]["to"] == "bob"

    def test_self_relation_dropped(self):
        raw = '{"entities": [{"name": "Ravi", "type": "Person"}], "relations": [{"from": "Ravi", "relation": "RELATED_TO", "to": "Ravi"}]}'
        assert parse_response(raw)["relations"] == []


class TestGraph:
    @pytest.fixture(autouse=True)
    def _clean_graph(self):
        graph._database = None
        if settings.graph_path.exists():
            settings.graph_path.unlink()
        yield
        graph._database = None
        if settings.graph_path.exists():
            settings.graph_path.unlink()

    def _seed(self):
        with graph.get_conn() as conn:
            conn.execute("CREATE (c:Capture {id: 100, is_latest: true})")
            conn.execute("CREATE (c:Capture {id: 101, is_latest: true})")
            conn.execute("CREATE (c:Capture {id: 102, is_latest: false})")
            conn.execute("CREATE (e:Entity {name: 'electricity bill', entity_type: 'Topic'})")
            conn.execute("CREATE (e:Entity {name: 'adani power', entity_type: 'Organization'})")
            conn.execute("CREATE (e:Entity {name: 'outage helpline', entity_type: 'Topic'})")
            for cid, name in [(100, "electricity bill"), (100, "adani power"), (101, "adani power"), (102, "electricity bill"), (101, "outage helpline")]:
                conn.execute(
                    "MATCH (c:Capture {id: $cid}), (e:Entity {name: $name}) CREATE (c)-[:MENTIONS]->(e)",
                    {"cid": cid, "name": name},
                )
            conn.execute(
                "MATCH (a:Entity {name: 'electricity bill'}), (b:Entity {name: 'adani power'}) "
                "MERGE (a)-[r:RELATES_TO]->(b) SET r.relation = 'ISSUED_BY'"
            )

    def test_schema_idempotent(self):
        for i in range(2):
            with graph.get_conn() as conn:
                conn.execute(f"CREATE (c:Capture {{id: {999 + i}, is_latest: true}})")

    def test_two_hop_and_latest_filter(self):
        self._seed()
        hits = graph.search(["electricity bill"])
        ids = [h["capture_id"] for h in hits]
        assert 100 in ids and 101 in ids
        assert 102 not in ids
        assert ids.index(100) < ids.index(101)

    def test_include_old_versions(self):
        self._seed()
        ids = [h["capture_id"] for h in graph.search(["electricity bill"], include_old_versions=True)]
        assert 102 in ids

    def test_empty_names(self):
        assert graph.search([]) == []

    def test_delete_capture_removes_node(self):
        self._seed()
        graph.delete_capture(100)
        hits = graph.search(["adani power"])
        ids = [h["capture_id"] for h in hits]
        assert 100 not in ids
        assert 101 in ids

class TestClassify:
    def test_high_id_documents(self):
        assert classify("My PAN number is ABCDE1234F") == "high"
        assert classify("Aadhaar 1234 5678 9012 verified") == "high"
        assert classify("Bank statement for account ACC-777") == "high"
        assert classify("electricity bill amount was 3500 rupees") == "high"

    def test_moderate_keywords(self):
        assert classify("meeting with Ravi on Friday") == "moderate"
        assert classify("doctor appointment at 5pm") == "moderate"

    def test_none(self):
        assert classify("Goa trip was in December with friends") == "none"
        assert classify("remember to buy milk") == "none"

    def test_empty(self):
        assert classify("") == "none"
        assert classify("   ") == "none"


class TestPin:
    def test_set_verify_clear_lifecycle(self):
        pin.clear_pin()
        assert not pin.is_set()
        pin.set_pin("4321")
        assert pin.is_set()
        assert pin.verify_pin("4321")
        assert not pin.verify_pin("0000")
        pin.set_pin("9999")
        assert pin.verify_pin("9999")
        assert not pin.verify_pin("4321")
        pin.clear_pin()
        assert not pin.is_set()
        assert not pin.verify_pin("9999")

    def test_token_roundtrip_and_invalid(self):
        pin.set_pin("1234")
        token = pin.issue_token()
        assert pin.token_valid(token)
        assert not pin.token_valid("garbage")
        assert not pin.token_valid(None)
        pin.clear_pin()
        assert not pin.token_valid(token)
