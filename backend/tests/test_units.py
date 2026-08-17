import pytest

from app import graph
from app.config import settings
from app.guardrails import pin
from app.ingestion.chunker import chunk_text
from app.ingestion.classify import classify
from app.ingestion.extract import parse_response
from app.retrieval.chat import NOT_FOUND_ANSWER, _parse_response
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


class TestChatParse:
    def test_valid_prose(self):
        answer, found, structured = _parse_response('{"kind": "prose", "answer": "Two projects [1]."}')
        assert found and answer == "Two projects [1]."
        assert structured["kind"] == "prose"

    def test_valid_fields(self):
        answer, found, structured = _parse_response(
            '{"kind": "fields", "answer": "PAN summary [1]", "fields": [{"key": "PAN", "value": "XXXX"}]}'
        )
        assert found and structured["kind"] == "fields"
        assert structured["fields"][0]["key"] == "PAN"

    def test_not_found(self):
        answer, found, structured = _parse_response('{"kind": "not_found"}')
        assert not found and answer == NOT_FOUND_ANSWER and structured is None

    def test_code_fence_wrapped(self):
        answer, found, _ = _parse_response('```json\n{"kind": "prose", "answer": "ok [1]"}\n```')
        assert found and answer == "ok [1]"

    def test_unparseable_raw_model_output_never_surfaces(self):
        answer, found, structured = _parse_response(
            'Sure! Here is the answer: {"kind": "prose", "answer": "recovered [1]"} and some trailing words'
        )
        assert found and answer == "recovered [1]"
        assert structured["kind"] == "prose"

    def test_total_junk_returns_not_found_not_raw_text(self):
        answer, found, structured = _parse_response("the resume text is: name email phone ...")
        assert not found and answer == NOT_FOUND_ANSWER and structured is None


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

    def test_restore_capture_flips_latest(self):
        self._seed()
        graph.restore_capture(102, [100, 101, 102])
        ids = [h["capture_id"] for h in graph.search(["electricity bill"])]
        assert 102 in ids
        assert 100 not in ids

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

    def test_keywords_match_words_not_substrings(self):
        assert classify("Skilled in Pandas and NumPy for data pipelines") == "none"
        assert classify("handled the tax returns for the firm") == "high"
        assert classify("shared my PAN card copy") == "high"
        assert classify("meeting notes for the sprint") == "moderate"

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


class TestOcrRouting:
    def test_image_routes_to_ocr_and_raises_when_disabled(self, tmp_path):
        from app.ingestion.ocr import extract_doc

        img = tmp_path / "scan.png"
        img.write_bytes(b"fake png bytes")
        with pytest.raises(ValueError, match="OCR is disabled"):
            extract_doc(img)

    def test_image_only_pdf_routes_to_ocr_when_disabled(self, tmp_path):
        from app.ingestion.ocr import extract_doc

        pdf = tmp_path / "scan.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake image-only pdf")
        with pytest.raises(ValueError, match="OCR is disabled"):
            extract_doc(pdf)

    def test_plain_text_uses_local_extraction(self, tmp_path):
        from app.ingestion.ocr import extract_doc

        note = tmp_path / "note.txt"
        note.write_text("plain text note with a text layer")
        assert "plain text note" in extract_doc(note)

    def test_cupsfilter_pdf_uses_local_extraction(self, tmp_path):
        from app.ingestion.ocr import extract_doc

        src = tmp_path / "doc.txt"
        src.write_text("PAN card ABCDE1234F")
        pdf = tmp_path / "doc.pdf"
        # cupsfilter writes the PDF to stdout, not to a file
        result = __import__("subprocess").run(
            ["cupsfilter", str(src)], check=True, capture_output=True
        )
        pdf.write_bytes(result.stdout)
        assert "PAN card" in extract_doc(pdf)

    def test_image_only_pdf_routes_to_ocr(self, tmp_path):
        import pymupdf

        from app.ingestion.ocr import extract_doc

        src = tmp_path / "doc.txt"
        src.write_text("PAN card ABCDE1234F")
        pdf = tmp_path / "doc.pdf"
        png = tmp_path / "doc.png"
        scanned = tmp_path / "scanned.pdf"
        result = __import__("subprocess").run(
            ["cupsfilter", str(src)], check=True, capture_output=True
        )
        pdf.write_bytes(result.stdout)
        with pymupdf.open(pdf) as doc:
            doc[0].get_pixmap(dpi=200).save(str(png))
        __import__("subprocess").run(
            ["sips", "-s", "format", "pdf", str(png), "--out", str(scanned)],
            check=True,
            capture_output=True,
        )
        with pytest.raises(ValueError, match="OCR is disabled"):
            extract_doc(scanned)
