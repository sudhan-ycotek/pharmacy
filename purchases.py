import datetime
import json
import os

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from auth import current_user, role_required
from db import get_db
from inventory import get_medicine_units, insert_batch, search_medicines, update_max_discount

bp = Blueprint("purchases", __name__, url_prefix="/purchases")

INR_TO_NPR_RATE = 1.60  # fixed India-Nepal peg: 1 INR = 1.60 NPR


def convert_to_npr(amount, currency):
    if currency not in ("NPR", "INR"):
        raise ValueError("currency must be 'NPR' or 'INR'")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount < 0:
        raise ValueError("cost price must be a non-negative number")
    return round(amount * INR_TO_NPR_RATE, 2) if currency == "INR" else round(amount, 2)


def _parse_bill_date(value):
    try:
        parsed = datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError("bill date must be in YYYY-MM-DD format")
    if parsed > datetime.date.today():
        raise ValueError("bill date cannot be in the future")
    return parsed.isoformat()


def _valid_percent(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100


def save_bill_image(purchase_bill_id, file_storage):
    from flask import current_app

    ext = os.path.splitext(file_storage.filename or "")[1].lower() or ".jpg"
    allowed_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    if ext not in allowed_exts:
        raise ValueError(f"unsupported file type '{ext}' — allowed types: {', '.join(sorted(allowed_exts))}")

    filename = f"bill_{purchase_bill_id}{ext}"
    bills_dir = os.path.join(current_app.static_folder, "purchase_bills")
    os.makedirs(bills_dir, exist_ok=True)
    file_storage.save(os.path.join(bills_dir, filename))
    return f"purchase_bills/{filename}"


def create_purchase_bill(user_id, vendor_id, bill_date, items, vendor_bill_reference=None,
                          bill_image_file=None, first_payment_amount=None,
                          first_payment_paid_at=None, first_payment_note=None):
    from vendors import get_vendor

    if not items:
        raise ValueError("purchase bill must include at least one medicine")
    bill_date_iso = _parse_bill_date(bill_date)
    if get_vendor(vendor_id) is None:
        raise ValueError(f"vendor {vendor_id} not found")
    if first_payment_amount is not None:
        if not isinstance(first_payment_amount, (int, float)) or isinstance(first_payment_amount, bool) \
                or first_payment_amount <= 0:
            raise ValueError("first payment amount must be positive")

    db = get_db()

    # --- validation pass: nothing is written until every item is confirmed valid ---
    prepared = []
    computed_total = 0.0
    for item in items:
        medicine_id = item["medicine_id"]
        unit_name = item["unit_name"]
        quantity = item["quantity"]
        expiry_date = item["expiry_date"]
        cost_currency = item.get("cost_currency", "NPR")
        cost_price_original = item["cost_price_original"]
        mrp_per_base_unit = item["mrp_per_base_unit"]
        max_discount_percent = item.get("max_discount_percent")

        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive whole number")
        if max_discount_percent is not None and not _valid_percent(max_discount_percent):
            raise ValueError("max discount percent must be between 0 and 100")

        unit_row = db.execute(
            "SELECT qty_in_base_units FROM medicine_units WHERE medicine_id = ? AND unit_name = ?",
            (medicine_id, unit_name),
        ).fetchone()
        if unit_row is None:
            raise ValueError(f"unknown unit '{unit_name}' for medicine {medicine_id}")

        cost_price_per_base_unit = convert_to_npr(cost_price_original, cost_currency)
        base_units = unit_row["qty_in_base_units"] * quantity
        computed_total += round(cost_price_per_base_unit * base_units, 2)
        prepared.append({
            "medicine_id": medicine_id, "unit_name": unit_name, "quantity": quantity,
            "expiry_date": expiry_date, "cost_currency": cost_currency,
            "cost_price_original": cost_price_original,
            "cost_price_per_base_unit": cost_price_per_base_unit,
            "mrp_per_base_unit": mrp_per_base_unit, "max_discount_percent": max_discount_percent,
        })

    bill_total = round(computed_total, 2)

    # --- write pass: one transaction, one commit ---
    cur = db.execute(
        "INSERT INTO purchase_bills (vendor_id, bill_date, vendor_bill_reference, bill_image_path, "
        "total_amount, recorded_by_user_id) VALUES (?, ?, ?, NULL, ?, ?)",
        (vendor_id, bill_date_iso, vendor_bill_reference, bill_total, user_id),
    )
    purchase_bill_id = cur.lastrowid

    if bill_image_file:
        image_path = save_bill_image(purchase_bill_id, bill_image_file)
        db.execute(
            "UPDATE purchase_bills SET bill_image_path = ? WHERE id = ?",
            (image_path, purchase_bill_id),
        )

    for p in prepared:
        insert_batch(
            db, p["medicine_id"], p["unit_name"], p["quantity"], p["expiry_date"],
            p["cost_price_per_base_unit"], p["mrp_per_base_unit"],
            purchase_bill_id=purchase_bill_id, cost_currency=p["cost_currency"],
            cost_price_original=round(p["cost_price_original"], 2),
        )
        if p["max_discount_percent"] is not None:
            update_max_discount(p["medicine_id"], p["max_discount_percent"])

    if first_payment_amount:
        _insert_payment(db, purchase_bill_id, first_payment_amount,
                         first_payment_paid_at or bill_date_iso, user_id, first_payment_note)

    db.commit()
    return {"purchase_bill_id": purchase_bill_id, "vendor_id": vendor_id, "total_amount": bill_total}


def _insert_payment(db, purchase_bill_id, amount, paid_at, user_id, note=None):
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
        raise ValueError("payment amount must be positive")
    due = bill_amount_due(purchase_bill_id)
    if amount > due + 0.01:
        raise ValueError("payment amount cannot exceed the amount due")
    db.execute(
        "INSERT INTO purchase_payments (purchase_bill_id, amount, paid_at, note, recorded_by_user_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (purchase_bill_id, round(amount, 2), paid_at, note, user_id),
    )


def record_payment(purchase_bill_id, amount, paid_at, user_id, note=None):
    db = get_db()
    _insert_payment(db, purchase_bill_id, amount, paid_at, user_id, note)
    db.commit()


def bill_total_paid(purchase_bill_id):
    db = get_db()
    row = db.execute(
        "SELECT COALESCE(SUM(amount), 0) AS paid FROM purchase_payments WHERE purchase_bill_id = ?",
        (purchase_bill_id,),
    ).fetchone()
    return row["paid"]


def bill_amount_due(purchase_bill_id):
    db = get_db()
    bill = db.execute(
        "SELECT total_amount FROM purchase_bills WHERE id = ?", (purchase_bill_id,)
    ).fetchone()
    return round(bill["total_amount"] - bill_total_paid(purchase_bill_id), 2)


def list_purchase_bills(vendor_id):
    db = get_db()
    return db.execute(
        """
        SELECT pb.*, v.name AS vendor_name, u.username AS recorded_by_username,
               COALESCE(payments.total_paid, 0) AS total_paid,
               pb.total_amount - COALESCE(payments.total_paid, 0) AS amount_due
        FROM purchase_bills pb
        JOIN vendors v ON v.id = pb.vendor_id
        JOIN users u ON u.id = pb.recorded_by_user_id
        LEFT JOIN (SELECT purchase_bill_id, SUM(amount) AS total_paid
                   FROM purchase_payments GROUP BY purchase_bill_id) payments
          ON payments.purchase_bill_id = pb.id
        WHERE pb.vendor_id = ?
        ORDER BY pb.bill_date DESC, pb.id DESC
        """,
        (vendor_id,),
    ).fetchall()


def vendor_balance(vendor_id):
    db = get_db()
    row = db.execute(
        """
        SELECT COALESCE(SUM(pb.total_amount), 0) AS total_billed,
               COALESCE(SUM(payments.total_paid), 0) AS total_paid
        FROM purchase_bills pb
        LEFT JOIN (SELECT purchase_bill_id, SUM(amount) AS total_paid
                   FROM purchase_payments GROUP BY purchase_bill_id) payments
          ON payments.purchase_bill_id = pb.id
        WHERE pb.vendor_id = ?
        """,
        (vendor_id,),
    ).fetchone()
    return {
        "total_billed": row["total_billed"], "total_paid": row["total_paid"],
        "total_due": round(row["total_billed"] - row["total_paid"], 2),
    }


def get_purchase_bill(purchase_bill_id):
    db = get_db()
    return db.execute(
        "SELECT pb.*, v.name AS vendor_name FROM purchase_bills pb "
        "JOIN vendors v ON v.id = pb.vendor_id WHERE pb.id = ?",
        (purchase_bill_id,),
    ).fetchone()


def list_batches_for_bill(purchase_bill_id):
    db = get_db()
    return db.execute(
        "SELECT mb.*, m.name AS medicine_name FROM medicine_batches mb "
        "JOIN medicines m ON m.id = mb.medicine_id WHERE mb.purchase_bill_id = ? ORDER BY mb.id",
        (purchase_bill_id,),
    ).fetchall()


def list_payments(purchase_bill_id):
    db = get_db()
    return db.execute(
        "SELECT * FROM purchase_payments WHERE purchase_bill_id = ? ORDER BY paid_at, id",
        (purchase_bill_id,),
    ).fetchall()


def search_medicines_for_purchase(query):
    results = []
    for m in search_medicines(query):
        units = get_medicine_units(m["id"])
        results.append({
            "id": m["id"], "name": m["name"], "packaging_type": m["packaging_type"],
            "max_discount_percent": m["max_discount_percent"],
            "units": [{"unit_name": u["unit_name"]} for u in units],
        })
    return results


@bp.route("/new")
@role_required("admin")
def new_purchase_bill_view():
    from vendors import list_vendors

    preselected_vendor_id = request.args.get("vendor_id", type=int)
    return render_template(
        "purchase_bill_new.html", vendors=list_vendors(), preselected_vendor_id=preselected_vendor_id
    )


@bp.route("/medicines/search")
@role_required("admin")
def search_medicines_view():
    return jsonify(search_medicines_for_purchase(request.args.get("q", "")))


@bp.route("", methods=["POST"])
@role_required("admin")
def create_purchase_bill_view():
    user = current_user()
    try:
        items = json.loads(request.form.get("items_json", "[]"))
        if not isinstance(items, list):
            raise ValueError("'items' must be a list")
        vendor_id = int(request.form["vendor_id"])
        bill_date = request.form["bill_date"]
        vendor_bill_reference = request.form.get("vendor_bill_reference") or None
        paid_amount = request.form.get("paid_amount")
        first_payment_amount = float(paid_amount) if paid_amount else None
        bill_image_file = request.files.get("bill_image")
        if bill_image_file is not None and not bill_image_file.filename:
            bill_image_file = None

        result = create_purchase_bill(
            user["id"], vendor_id, bill_date, items,
            vendor_bill_reference=vendor_bill_reference,
            bill_image_file=bill_image_file,
            first_payment_amount=first_payment_amount,
            first_payment_paid_at=bill_date,
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@bp.route("/<int:purchase_bill_id>")
@role_required("admin")
def purchase_bill_detail_view(purchase_bill_id):
    bill = get_purchase_bill(purchase_bill_id)
    if bill is None:
        return "Purchase bill not found", 404
    return render_template(
        "purchase_bill_detail.html", bill=bill,
        batches=list_batches_for_bill(purchase_bill_id),
        payments=list_payments(purchase_bill_id),
        total_paid=bill_total_paid(purchase_bill_id),
        amount_due=bill_amount_due(purchase_bill_id),
    )


@bp.route("/<int:purchase_bill_id>/payments", methods=["POST"])
@role_required("admin")
def add_payment_view(purchase_bill_id):
    user = current_user()
    try:
        record_payment(
            purchase_bill_id, float(request.form["amount"]),
            request.form.get("paid_at") or datetime.date.today().isoformat(),
            user["id"], request.form.get("note") or None,
        )
    except (ValueError, KeyError, TypeError) as e:
        flash(str(e))
    return redirect(url_for("purchases.purchase_bill_detail_view", purchase_bill_id=purchase_bill_id))
