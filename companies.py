import sqlite3

from flask import Blueprint, jsonify, request

from auth import role_required
from db import get_db

bp = Blueprint("companies", __name__, url_prefix="/companies")


def _next_company_code(db):
    """3-digit zero-padded code: MAX(existing numeric code) + 1.

    Widens past "999" to "1000" rather than blocking once the numeric part
    outgrows 3 digits -- the same widen-rather-than-block approach db.py's
    vendor code backfill uses for its own (differently formatted) codes.
    """
    row = db.execute("SELECT MAX(CAST(code AS INTEGER)) AS max_code FROM companies").fetchone()
    next_number = (row["max_code"] or 0) + 1
    return f"{next_number:03d}"


def _insert_company(db, name, phone=None, address=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("company name is required")
    code = _next_company_code(db)
    try:
        cur = db.execute(
            "INSERT INTO companies (code, name, phone, address) VALUES (?, ?, ?, ?)",
            (code, name, (phone or "").strip() or None, (address or "").strip() or None),
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"company '{name}' already exists")
    return cur.lastrowid


def add_company(name, phone=None, address=None):
    db = get_db()
    company_id = _insert_company(db, name, phone, address)
    db.commit()
    return company_id


def list_companies():
    db = get_db()
    return db.execute("SELECT * FROM companies ORDER BY name").fetchall()


def get_company(company_id):
    db = get_db()
    return db.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()


def search_companies(query):
    db = get_db()
    return db.execute(
        "SELECT * FROM companies WHERE name LIKE ? ORDER BY name",
        (f"%{query}%",),
    ).fetchall()


@bp.route("/search", methods=["GET"])
@role_required("admin")
def search_companies_view():
    return jsonify([dict(c) for c in search_companies(request.args.get("q", ""))])


@bp.route("", methods=["POST"])
@role_required("admin")
def add_company_view():
    payload = request.get_json(silent=True) or {}
    try:
        company_id = add_company(payload.get("name", ""), payload.get("phone"), payload.get("address"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    company = get_company(company_id)
    return jsonify({"id": company_id, "name": company["name"], "code": company["code"]})
