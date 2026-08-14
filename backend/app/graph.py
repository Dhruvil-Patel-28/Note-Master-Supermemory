import logging
from contextlib import contextmanager

import ladybug

from . import db
from .config import settings
from .ingestion.extract import extract, normalize

logger = logging.getLogger(__name__)

_SCHEMA = [
    "CREATE NODE TABLE IF NOT EXISTS Capture(id INT64 PRIMARY KEY, is_latest BOOLEAN)",
    "CREATE NODE TABLE IF NOT EXISTS Entity(name STRING PRIMARY KEY, entity_type STRING)",
    "CREATE REL TABLE IF NOT EXISTS MENTIONS(FROM Capture TO Entity)",
    "CREATE REL TABLE IF NOT EXISTS RELATES_TO(FROM Entity TO Entity, relation STRING)",
]

_database: ladybug.Database | None = None


def _db() -> ladybug.Database:
    global _database
    if _database is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _database = ladybug.Database(str(settings.graph_path))
    return _database


@contextmanager
def get_conn() -> ladybug.Connection:
    conn = ladybug.Connection(_db())
    for stmt in _SCHEMA:
        conn.execute(stmt)
    try:
        yield conn
    finally:
        conn.close()


def _rows(conn: ladybug.Connection, cypher: str, params: dict | None = None) -> list[dict]:
    result = conn.execute(cypher, params or {})
    columns = result.get_column_names()
    rows = []
    while result.has_next():
        row = result.get_next()
        rows.append(dict(zip(columns, row)))
    return rows


def write_capture(capture_id: int, content: str, sibling_ids: list[int]) -> None:
    data = extract(content)
    names = [e["name"] for e in data["entities"]]
    with get_conn() as conn:
        conn.execute("MATCH (c:Capture {id: $id}) DETACH DELETE c", {"id": capture_id})
        for sid in sibling_ids:
            conn.execute(
                "MATCH (c:Capture {id: $sid}) SET c.is_latest = false", {"sid": sid}
            )
        conn.execute(
            "CREATE (c:Capture {id: $id, is_latest: true})",
            {"id": capture_id},
        )
        for ent in data["entities"]:
            conn.execute(
                "MERGE (e:Entity {name: $name}) SET e.entity_type = $etype",
                {"name": ent["name"], "etype": ent["type"]},
            )
            conn.execute(
                "MATCH (c:Capture {id: $id}), (e:Entity {name: $name}) CREATE (c)-[:MENTIONS]->(e)",
                {"id": capture_id, "name": ent["name"]},
            )
        for rel in data["relations"]:
            conn.execute(
                "MATCH (a:Entity {name: $from}), (b:Entity {name: $to}) "
                "MERGE (a)-[r:RELATES_TO]->(b) SET r.relation = $relation",
                {"from": rel["from"], "to": rel["to"], "relation": rel["relation"]},
            )
    if names:
        logger.info("graph: capture %s linked to %d entities", capture_id, len(names))


def delete_capture(capture_id: int) -> None:
    try:
        with get_conn() as conn:
            conn.execute("MATCH (c:Capture {id: $id}) DETACH DELETE c", {"id": capture_id})
    except Exception as exc:
        logger.warning("graph delete failed for capture %s: %s", capture_id, exc)


def search(
    entity_names: list[str],
    limit: int = 10,
    include_old_versions: bool = False,
) -> list[dict]:
    names = [normalize(n) for n in entity_names if normalize(n)]
    if not names:
        return []
    latest = "" if include_old_versions else "{is_latest: true}"
    hits: list[dict] = []
    with get_conn() as conn:
        one = _rows(
            conn,
            f"MATCH (c:Capture{latest})-[:MENTIONS]->(e:Entity) "
            "WHERE e.name IN $names RETURN DISTINCT c.id AS id",
            {"names": names},
        )
        two = _rows(
            conn,
            f"MATCH (c:Capture{latest})-[:MENTIONS]->(e2:Entity)-[:RELATES_TO]-(e:Entity) "
            "WHERE e.name IN $names RETURN DISTINCT c.id AS id",
            {"names": names},
        )
    seen = set()
    for row in one + two:
        cid = row["id"]
        if cid in seen:
            continue
        seen.add(cid)
        hits.append({"capture_id": cid, "snippet": _snippet(cid), "score": 0.0})
    return hits[:limit]


def _snippet(capture_id: int) -> str:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT text FROM capture_chunks WHERE capture_id = ? ORDER BY chunk_index LIMIT 1",
            (capture_id,),
        ).fetchone()
    return row["text"][:300] if row else ""