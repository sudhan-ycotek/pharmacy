# tests/test_db.py
from db import get_db

EXPECTED_TABLES = {
    "users", "medicines", "medicine_units",
    "sales", "sale_items", "photo_tokens",
}


def test_init_db_creates_expected_tables(app):
    with app.app_context():
        conn = get_db()
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert EXPECTED_TABLES <= tables
