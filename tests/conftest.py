import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app import create_app
from auth import create_user


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


@pytest.fixture
def admin_user(app):
    with app.app_context():
        create_user("admin", "adminpass", "admin")


@pytest.fixture
def staff_user(app):
    with app.app_context():
        create_user("staff1", "staffpass", "staff")


@pytest.fixture
def admin_client(client, admin_user):
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    return client


@pytest.fixture
def staff_client(client, staff_user):
    client.post("/login", data={"username": "staff1", "password": "staffpass"})
    return client
