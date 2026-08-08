import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    db_path = tmp_path / "test.db"
    return create_app({
        "TESTING": True,
        "DATABASE": str(db_path),
        "SECRET_KEY": "test",
    })


@pytest.fixture
def client(app):
    return app.test_client()
