import os
import tempfile

import pytest

os.environ["NOTE_MASTER_DATA_DIR"] = tempfile.mkdtemp(prefix="note_master_test_")
os.environ["OCR_ENABLED"] = "0"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    from app.db import get_conn

    return get_conn