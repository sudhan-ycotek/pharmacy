import sqlite3

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

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


def _insert_company(db, name, phone=None, address=None, contact_person=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("company name is required")
    code = _next_company_code(db)
    try:
        cur = db.execute(
            "INSERT INTO companies (code, name, phone, address, contact_person) VALUES (?, ?, ?, ?, ?)",
            (code, name, (phone or "").strip() or None, (address or "").strip() or None,
             (contact_person or "").strip() or None),
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"company '{name}' already exists")
    return cur.lastrowid


def add_company(name, phone=None, address=None, contact_person=None):
    db = get_db()
    company_id = _insert_company(db, name, phone, address, contact_person)
    db.commit()
    return company_id


def edit_company(company_id, name, phone=None, address=None, contact_person=None):
    db = get_db()
    if get_company(company_id) is None:
        raise ValueError(f"company {company_id} not found")
    name = (name or "").strip()
    if not name:
        raise ValueError("company name is required")
    try:
        db.execute(
            "UPDATE companies SET name = ?, phone = ?, address = ?, contact_person = ? WHERE id = ?",
            (name, (phone or "").strip() or None, (address or "").strip() or None,
             (contact_person or "").strip() or None, company_id),
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"company '{name}' already exists")
    db.commit()


def get_company_vendors(company_id):
    db = get_db()
    return db.execute(
        "SELECT v.* FROM vendors v "
        "JOIN company_vendors cv ON cv.vendor_id = v.id "
        "WHERE cv.company_id = ? ORDER BY v.name",
        (company_id,),
    ).fetchall()


def set_company_vendors(company_id, vendor_ids):
    """Replace this company's vendor links with exactly the given set.

    Deleting and re-inserting keeps this idempotent and avoids diffing old
    vs. new membership -- fine at the size these link tables run at.
    """
    db = get_db()
    vendor_ids = list(dict.fromkeys(vendor_ids))
    for vendor_id in vendor_ids:
        if db.execute("SELECT 1 FROM vendors WHERE id = ?", (vendor_id,)).fetchone() is None:
            raise ValueError(f"vendor {vendor_id} not found")
    db.execute("DELETE FROM company_vendors WHERE company_id = ?", (company_id,))
    for vendor_id in vendor_ids:
        db.execute(
            "INSERT INTO company_vendors (company_id, vendor_id) VALUES (?, ?)",
            (company_id, vendor_id),
        )
    db.commit()


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


def _vendor_ids_from_form(form):
    ids = []
    for raw in form.getlist("vendor_ids"):
        try:
            ids.append(int(raw))
        except ValueError:
            continue
    return ids


@bp.route("", methods=["GET"])
@role_required("admin")
def list_companies_view():
    from vendors import list_vendors

    q = request.args.get("q", "")
    companies = search_companies(q) if q else list_companies()
    vendors_by_company = {c["id"]: get_company_vendors(c["id"]) for c in companies}
    return render_template(
        "companies.html", companies=companies, vendors_by_company=vendors_by_company,
        q=q, all_vendors=list_vendors(),
    )


@bp.route("/add", methods=["GET", "POST"])
@role_required("admin")
def add_company_form_view():
    from vendors import list_vendors

    if request.method == "POST":
        try:
            company_id = add_company(
                request.form.get("name", ""), request.form.get("phone"),
                request.form.get("address"), request.form.get("contact_person"),
            )
            set_company_vendors(company_id, _vendor_ids_from_form(request.form))
            return redirect(url_for("companies.list_companies_view"))
        except ValueError as e:
            flash(str(e))
    return render_template(
        "company_form.html", company=None, linked_vendor_ids=set(), all_vendors=list_vendors(),
    )


@bp.route("/<int:company_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_company_view(company_id):
    from vendors import list_vendors

    company = get_company(company_id)
    if company is None:
        return "Company not found", 404

    if request.method == "POST":
        try:
            edit_company(
                company_id, request.form.get("name", ""), request.form.get("phone"),
                request.form.get("address"), request.form.get("contact_person"),
            )
            set_company_vendors(company_id, _vendor_ids_from_form(request.form))
            return redirect(url_for("companies.list_companies_view"))
        except ValueError as e:
            flash(str(e))
    linked_vendor_ids = {v["id"] for v in get_company_vendors(company_id)}
    return render_template(
        "company_form.html", company=company, linked_vendor_ids=linked_vendor_ids,
        all_vendors=list_vendors(),
    )
