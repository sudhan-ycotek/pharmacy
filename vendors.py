import sqlite3

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from auth import role_required
from db import get_db

bp = Blueprint("vendors", __name__, url_prefix="/vendors")

PAY_MODES = ("cash", "bank_transfer", "cheque", "digital_wallet")


def _validate_pay_mode(pay_mode):
    if pay_mode is not None and pay_mode not in PAY_MODES:
        raise ValueError(f"pay_mode must be one of {', '.join(PAY_MODES)}")


def _next_vendor_code(db):
    """SUP-#### code: MAX(existing numeric suffix) + 1.

    Widens past 4 digits ("SUP-9999" -> "SUP-10000") rather than blocking once
    the numeric part outgrows 4 digits -- the exact same numbering scheme
    db.py's _backfill_vendor_codes migration uses for legacy vendors, so
    forward-generated and migration-backfilled codes never collide or drift
    into a different format.
    """
    existing_numbers = []
    for row in db.execute("SELECT code FROM vendors WHERE code IS NOT NULL"):
        code = row["code"]
        if code and code.startswith("SUP-") and code[4:].isdigit():
            existing_numbers.append(int(code[4:]))
    next_number = max(existing_numbers, default=0) + 1
    return f"SUP-{next_number:04d}"


def _insert_vendor(db, name, phone=None, address=None, email=None, pan_number=None,
                    bank_account_number=None, pay_mode=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("vendor name is required")
    _validate_pay_mode(pay_mode)
    code = _next_vendor_code(db)
    try:
        cur = db.execute(
            "INSERT INTO vendors (name, phone, address, code, email, pan_number, "
            "bank_account_number, pay_mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, (phone or "").strip() or None, (address or "").strip() or None, code,
             (email or "").strip() or None, (pan_number or "").strip() or None,
             (bank_account_number or "").strip() or None, pay_mode or None),
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"vendor '{name}' already exists")
    return cur.lastrowid


def add_vendor(name, phone=None, address=None, email=None, pan_number=None,
               bank_account_number=None, pay_mode=None):
    db = get_db()
    vendor_id = _insert_vendor(db, name, phone, address, email, pan_number,
                                bank_account_number, pay_mode)
    db.commit()
    return vendor_id


def edit_vendor(vendor_id, name, phone=None, address=None, email=None, pan_number=None,
                 bank_account_number=None, pay_mode=None):
    db = get_db()
    if get_vendor(vendor_id) is None:
        raise ValueError(f"vendor {vendor_id} not found")
    name = (name or "").strip()
    if not name:
        raise ValueError("vendor name is required")
    _validate_pay_mode(pay_mode)
    try:
        db.execute(
            "UPDATE vendors SET name = ?, phone = ?, address = ?, email = ?, pan_number = ?, "
            "bank_account_number = ?, pay_mode = ? WHERE id = ?",
            (name, (phone or "").strip() or None, (address or "").strip() or None,
             (email or "").strip() or None, (pan_number or "").strip() or None,
             (bank_account_number or "").strip() or None, pay_mode or None, vendor_id),
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"vendor '{name}' already exists")
    db.commit()


def list_vendors():
    db = get_db()
    return db.execute("SELECT * FROM vendors ORDER BY name").fetchall()


def get_vendor(vendor_id):
    db = get_db()
    return db.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()


def search_vendors(query):
    db = get_db()
    return db.execute(
        "SELECT * FROM vendors WHERE name LIKE ? OR code LIKE ? ORDER BY name",
        (f"%{query}%", f"%{query}%"),
    ).fetchall()


@bp.route("/search", methods=["GET"])
@role_required("admin")
def search_vendors_view():
    return jsonify([dict(v) for v in search_vendors(request.args.get("q", ""))])


@bp.route("", methods=["GET"])
@role_required("admin")
def list_vendors_view():
    from purchases import vendor_balance

    q = request.args.get("q", "")
    vendors = search_vendors(q) if q else list_vendors()
    balances = {v["id"]: vendor_balance(v["id"]) for v in vendors}
    return render_template("vendors.html", vendors=vendors, balances=balances, q=q)


@bp.route("", methods=["POST"])
@role_required("admin")
def add_vendor_view():
    payload = request.get_json(silent=True) or {}
    try:
        vendor_id = add_vendor(payload.get("name", ""), payload.get("phone"), payload.get("address"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"id": vendor_id, "name": get_vendor(vendor_id)["name"]})


def _parse_vendor_form(form):
    return {
        "phone": form.get("phone"),
        "address": form.get("address"),
        "email": form.get("email"),
        "pan_number": form.get("pan_number"),
        "bank_account_number": form.get("bank_account_number"),
        "pay_mode": form.get("pay_mode") or None,
    }


@bp.route("/add", methods=["GET", "POST"])
@role_required("admin")
def add_vendor_form_view():
    if request.method == "POST":
        try:
            vendor_id = add_vendor(request.form.get("name", ""), **_parse_vendor_form(request.form))
            return redirect(url_for("vendors.vendor_detail_view", vendor_id=vendor_id))
        except ValueError as e:
            flash(str(e))
    return render_template("vendor_form.html", vendor=None, pay_modes=PAY_MODES)


@bp.route("/<int:vendor_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_vendor_view(vendor_id):
    vendor = get_vendor(vendor_id)
    if vendor is None:
        return "Vendor not found", 404

    if request.method == "POST":
        try:
            edit_vendor(vendor_id, request.form.get("name", ""), **_parse_vendor_form(request.form))
            return redirect(url_for("vendors.vendor_detail_view", vendor_id=vendor_id))
        except ValueError as e:
            flash(str(e))
    return render_template("vendor_form.html", vendor=vendor, pay_modes=PAY_MODES)


@bp.route("/<int:vendor_id>", methods=["GET"])
@role_required("admin")
def vendor_detail_view(vendor_id):
    from purchases import list_purchase_bills, vendor_balance

    vendor = get_vendor(vendor_id)
    if vendor is None:
        return "Vendor not found", 404
    return render_template(
        "vendor_detail.html", vendor=vendor,
        bills=list_purchase_bills(vendor_id), balance=vendor_balance(vendor_id),
    )
