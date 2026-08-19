import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import settings

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


def connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        for col, ddl in {
            "original_filename": "ALTER TABLE captures ADD COLUMN original_filename TEXT",
            "note": "ALTER TABLE captures ADD COLUMN note TEXT",
            "memory_doc_ids": "ALTER TABLE captures ADD COLUMN memory_doc_ids TEXT",
            "sensitive_facts": "ALTER TABLE captures ADD COLUMN sensitive_facts TEXT",
        }.items():
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass