import sqlite3

from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(schema_path):
    db = get_db()
    with open(schema_path) as f:
        db.executescript(f.read())
    db.commit()


def _table_columns(db, table):
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(db, table, column, definition):
    """ALTER TABLE ... ADD COLUMN, but only if it isn't there already.

    SQLite's ADD COLUMN accepts constant DEFAULT/CHECK clauses but not
    UNIQUE/PRIMARY KEY -- callers needing uniqueness must add a separate
    CREATE UNIQUE INDEX IF NOT EXISTS statement instead.
    """
    if column not in _table_columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _backfill_vendor_codes(db):
    """Assign SUP-#### codes to any legacy vendor rows that don't have one yet.

    Numbering continues from the highest existing "SUP-####" suffix (max + 1),
    the same widen-rather-than-block approach used elsewhere for auto codes:
    once the numeric part passes 9999 it simply grows to 5+ digits instead of
    blocking. Rows that already have a code are left untouched, so calling
    this repeatedly is a no-op once every vendor has one.
    """
    existing_numbers = []
    for row in db.execute("SELECT code FROM vendors WHERE code IS NOT NULL"):
        code = row["code"]
        if code and code.startswith("SUP-") and code[4:].isdigit():
            existing_numbers.append(int(code[4:]))
    next_number = max(existing_numbers, default=0) + 1

    rows = db.execute("SELECT id FROM vendors WHERE code IS NULL ORDER BY id").fetchall()
    for row in rows:
        db.execute(
            "UPDATE vendors SET code = ? WHERE id = ?",
            (f"SUP-{next_number:04d}", row["id"]),
        )
        next_number += 1


def run_migrations(db):
    """Bring an existing pharmacy.db up to the current schema.sql shape.

    Additive only -- never drops, renames, or narrows an existing column or
    table. Safe to call on every app startup: a fresh database (already
    created from the current schema.sql) sees every check already satisfied
    and every statement below is a no-op, and calling it more than once on the
    same database produces the same end state as calling it once.
    """
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL UNIQUE,
            phone TEXT,
            address TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
        """
    )

    _add_column_if_missing(db, "medicines", "company_id", "INTEGER REFERENCES companies(id)")
    _add_column_if_missing(db, "medicines", "packing", "TEXT")

    _add_column_if_missing(db, "vendors", "code", "TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_vendors_code ON vendors(code)")
    _backfill_vendor_codes(db)

    _add_column_if_missing(db, "stock_receipts", "batch_number", "TEXT")
    _add_column_if_missing(db, "stock_receipts", "expiry_date", "TEXT")
    _add_column_if_missing(
        db, "stock_receipts", "mrp_currency",
        "TEXT NOT NULL DEFAULT 'NPR' CHECK(mrp_currency IN ('NPR', 'INR'))",
    )
    _add_column_if_missing(db, "stock_receipts", "mrp_original", "REAL")
    db.execute(
        "UPDATE stock_receipts SET mrp_original = mrp_per_base_unit WHERE mrp_original IS NULL"
    )

    _add_column_if_missing(db, "purchase_return_items", "batch_number", "TEXT")

    _add_column_if_missing(db, "sales", "doctor_name", "TEXT")
    _add_column_if_missing(
        db, "sales", "payment_method",
        "TEXT NOT NULL DEFAULT 'cash' CHECK(payment_method IN ('cash', 'online'))",
    )
    _add_column_if_missing(db, "sales", "tender_amount", "REAL")
    _add_column_if_missing(db, "sales", "change_amount", "REAL")

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS sale_returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL REFERENCES sales(id),
            return_date TEXT NOT NULL,
            reason TEXT,
            total_amount REAL NOT NULL DEFAULT 0 CHECK(total_amount >= 0),
            recorded_by_user_id INTEGER NOT NULL REFERENCES users(id),
            voided INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS sale_return_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_return_id INTEGER NOT NULL REFERENCES sale_returns(id),
            sale_item_id INTEGER NOT NULL REFERENCES sale_items(id),
            medicine_id INTEGER NOT NULL REFERENCES medicines(id),
            unit_name TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            qty_in_base_units INTEGER NOT NULL,
            base_units_returned INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            amount REAL NOT NULL
        )
        """
    )

    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_purchase_bills_bill_date ON purchase_bills(bill_date)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_stock_receipts_purchase_bill_id "
        "ON stock_receipts(purchase_bill_id)"
    )

    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
