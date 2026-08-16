# tests/test_db.py
import sqlite3

from db import get_db, run_migrations

EXPECTED_TABLES = {
    "users", "companies", "medicines", "medicine_units", "stock_receipts",
    "vendors", "purchase_bills", "purchase_payments",
    "purchase_returns", "purchase_return_items", "stock_adjustments",
    "sales", "sale_items", "sale_returns", "sale_return_items", "photo_tokens",
    "company_vendors",
}

# The pre-Task-1 schema.sql shape: no `companies` table, no `sale_returns`/
# `sale_return_items` tables, and none of the new columns on `medicines`,
# `vendors`, `stock_receipts`, `purchase_return_items`, or `sales`. Used to
# prove run_migrations() actually transforms an old database rather than
# just matching a freshly-created one.
LEGACY_SCHEMA_SQL = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'staff'))
);

CREATE TABLE medicines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    packaging_type TEXT NOT NULL CHECK(packaging_type IN ('box_file', 'bottled_other')),
    photo_path TEXT,
    stock_in_base_units INTEGER NOT NULL DEFAULT 0,
    low_stock_threshold INTEGER NOT NULL DEFAULT 10,
    max_discount_percent REAL NOT NULL DEFAULT 0 CHECK(max_discount_percent >= 0 AND max_discount_percent <= 100),
    cost_price_per_base_unit REAL NOT NULL DEFAULT 0 CHECK(cost_price_per_base_unit >= 0),
    mrp_per_base_unit REAL NOT NULL DEFAULT 0 CHECK(mrp_per_base_unit >= 0)
);

CREATE TABLE medicine_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    qty_in_base_units INTEGER NOT NULL,
    is_sellable INTEGER NOT NULL DEFAULT 1,
    UNIQUE(medicine_id, unit_name)
);

CREATE TABLE vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    phone TEXT,
    address TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE purchase_bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    bill_date TEXT NOT NULL,
    vendor_bill_reference TEXT,
    bill_image_path TEXT,
    total_amount REAL NOT NULL DEFAULT 0 CHECK(total_amount >= 0),
    recorded_by_user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE stock_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    qty_in_base_units INTEGER NOT NULL,
    base_units_received INTEGER NOT NULL,
    cost_currency TEXT NOT NULL DEFAULT 'NPR' CHECK(cost_currency IN ('NPR', 'INR')),
    cost_price_original REAL NOT NULL CHECK(cost_price_original >= 0),
    cost_price_per_base_unit REAL NOT NULL CHECK(cost_price_per_base_unit >= 0),
    mrp_per_base_unit REAL NOT NULL CHECK(mrp_per_base_unit >= 0),
    purchase_bill_id INTEGER REFERENCES purchase_bills(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE purchase_returns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_bill_id INTEGER NOT NULL REFERENCES purchase_bills(id),
    return_date TEXT NOT NULL,
    reason TEXT,
    total_amount REAL NOT NULL DEFAULT 0 CHECK(total_amount >= 0),
    recorded_by_user_id INTEGER NOT NULL REFERENCES users(id),
    voided INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE purchase_return_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_return_id INTEGER NOT NULL REFERENCES purchase_returns(id),
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    qty_in_base_units INTEGER NOT NULL,
    base_units_returned INTEGER NOT NULL,
    cost_price_per_base_unit REAL NOT NULL,
    amount REAL NOT NULL
);

CREATE TABLE stock_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    qty_in_base_units INTEGER NOT NULL,
    base_units_delta INTEGER NOT NULL,
    reason TEXT NOT NULL CHECK(reason IN ('damaged', 'lost', 'found', 'correction', 'other')),
    note TEXT,
    recorded_by_user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE purchase_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_bill_id INTEGER NOT NULL REFERENCES purchase_bills(id),
    amount REAL NOT NULL CHECK(amount > 0),
    paid_at TEXT NOT NULL,
    note TEXT,
    recorded_by_user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    timestamp TEXT NOT NULL,
    patient_name TEXT,
    subtotal_before_discount REAL NOT NULL DEFAULT 0,
    discount_mode TEXT NOT NULL DEFAULT 'none' CHECK(discount_mode IN ('none', 'item', 'bill')),
    bill_discount_percent REAL NOT NULL DEFAULT 0,
    discount_amount REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL,
    voided INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    qty_in_base_units INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    cost_price_per_base_unit REAL NOT NULL,
    mrp_per_base_unit REAL NOT NULL,
    gross_unit_price REAL NOT NULL,
    discount_percent REAL NOT NULL DEFAULT 0,
    unit_price REAL NOT NULL,
    subtotal REAL NOT NULL
);

CREATE TABLE photo_tokens (
    token TEXT PRIMARY KEY,
    photo_path TEXT,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
"""


def _legacy_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(LEGACY_SCHEMA_SQL)
    conn.commit()
    return conn


def _table_names(conn):
    return {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _index_names(conn):
    return {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}


def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _schema_snapshot(conn):
    """A dict of every table/index name -> its exact CREATE statement, plus
    every row currently in sqlite_master's companion tables that matter for
    idempotency (here just the DDL is enough, since run_migrations() only
    ever adds structure, never rewrites data after the first backfill)."""
    return {
        row["name"]: row["sql"]
        for row in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
        )
    }


def test_init_db_creates_expected_tables(app):
    with app.app_context():
        conn = get_db()
        tables = _table_names(conn)
    assert EXPECTED_TABLES <= tables


def test_run_migrations_brings_legacy_db_up_to_current_shape():
    conn = _legacy_db()

    run_migrations(conn)

    assert EXPECTED_TABLES <= _table_names(conn)
    assert {"company_id", "packing", "code"} <= _columns(conn, "medicines")
    assert {"code", "email", "pan_number", "bank_account_number", "pay_mode"} <= _columns(conn, "vendors")
    assert "contact_person" in _columns(conn, "companies")
    assert {"batch_number", "expiry_date", "mrp_currency", "mrp_original"} <= _columns(
        conn, "stock_receipts"
    )
    assert "batch_number" in _columns(conn, "purchase_return_items")
    assert {
        "doctor_name", "payment_method", "tender_amount", "change_amount", "receipt_number",
    } <= _columns(conn, "sales")
    assert {
        "idx_vendors_code", "idx_medicines_code", "idx_sales_receipt_number",
        "idx_purchase_bills_bill_date", "idx_stock_receipts_purchase_bill_id",
    } <= _index_names(conn)

    conn.close()


def test_run_migrations_backfills_vendor_codes_and_mrp_original():
    conn = _legacy_db()
    conn.execute(
        "INSERT INTO vendors (name, phone, address) VALUES ('Acme Pharma', '000', 'Somewhere')"
    )
    conn.execute(
        "INSERT INTO medicines (name, packaging_type, mrp_per_base_unit) "
        "VALUES ('Cetamol', 'box_file', 2.5)"
    )
    conn.execute(
        "INSERT INTO stock_receipts "
        "(medicine_id, unit_name, quantity, qty_in_base_units, base_units_received, "
        " cost_price_original, cost_price_per_base_unit, mrp_per_base_unit) "
        "VALUES (1, 'Box', 1, 10, 10, 1.0, 0.1, 2.5)"
    )
    conn.commit()

    run_migrations(conn)

    vendor_row = conn.execute("SELECT code FROM vendors WHERE name = 'Acme Pharma'").fetchone()
    assert vendor_row["code"] == "SUP-0001"

    medicine_row = conn.execute("SELECT code FROM medicines WHERE name = 'Cetamol'").fetchone()
    assert medicine_row["code"] == "MED-0001"

    receipt_row = conn.execute("SELECT mrp_original FROM stock_receipts WHERE id = 1").fetchone()
    assert receipt_row["mrp_original"] == 2.5

    conn.close()


def test_run_migrations_backfills_receipt_numbers_by_sale_date():
    conn = _legacy_db()
    conn.execute(
        "INSERT INTO users (username, password_hash, role) VALUES ('cashier', 'x', 'staff')"
    )
    conn.execute(
        "INSERT INTO sales (user_id, timestamp, total) VALUES (1, '2026-03-05 09:00:00', 10)"
    )
    conn.execute(
        "INSERT INTO sales (user_id, timestamp, total) VALUES (1, '2026-03-05 15:00:00', 20)"
    )
    conn.commit()

    run_migrations(conn)

    rows = conn.execute("SELECT id, receipt_number FROM sales ORDER BY id").fetchall()
    assert rows[0]["receipt_number"] == "MEDGLO-0305-KHAR-0001"
    assert rows[1]["receipt_number"] == "MEDGLO-0305-KHAR-0002"

    conn.close()


def test_run_migrations_is_idempotent():
    conn = _legacy_db()
    conn.execute(
        "INSERT INTO vendors (name, phone, address) VALUES ('Acme Pharma', '000', 'Somewhere')"
    )
    conn.commit()

    run_migrations(conn)
    snapshot_after_first_call = _schema_snapshot(conn)
    vendor_code_after_first_call = conn.execute(
        "SELECT code FROM vendors WHERE name = 'Acme Pharma'"
    ).fetchone()["code"]

    run_migrations(conn)
    run_migrations(conn)

    assert _schema_snapshot(conn) == snapshot_after_first_call
    assert EXPECTED_TABLES <= _table_names(conn)
    vendor_code_after_more_calls = conn.execute(
        "SELECT code FROM vendors WHERE name = 'Acme Pharma'"
    ).fetchone()["code"]
    assert vendor_code_after_more_calls == vendor_code_after_first_call

    conn.close()


def test_run_migrations_is_a_noop_on_a_freshly_created_db(app):
    with app.app_context():
        conn = get_db()
        snapshot_before = _schema_snapshot(conn)

        run_migrations(conn)

        assert _schema_snapshot(conn) == snapshot_before
