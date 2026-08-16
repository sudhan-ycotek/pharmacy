import datetime
import json
import os

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from auth import current_user, role_required
from db import get_db
from inventory import _apply_stock_receipt, get_medicine_units, search_medicines, update_max_discount

bp = Blueprint("purchases", __name__, url_prefix="/purchases")

INR_TO_NPR_RATE = 1.60  # fixed India-Nepal peg: 1 INR = 1.60 NPR

RETURN_REASONS = ("damaged", "wrong_item", "vendor_recall", "other")


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


def _parse_expiry_date(value):
    """Normalize an optional per-item expiry date, or raise if given but malformed.

    Validated here (in create_purchase_bill's validation pass, before any writes)
    as well as inside _apply_stock_receipt itself -- the same belt-and-suspenders
    approach bill_date already gets, so a bad expiry on item 2 of a multi-item
    bill can't leave item 1's stock receipt partially committed.
    """
    if value is None or value == "":
        return None
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise ValueError("expiry date must be in YYYY-MM-DD format")


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
        cost_currency = item.get("cost_currency", "NPR")
        cost_price_original = item["cost_price_original"]
        mrp_currency = item.get("mrp_currency", "NPR")
        mrp_original = item["mrp_original"]
        max_discount_percent = item.get("max_discount_percent")
        batch_number = (item.get("batch_number") or "").strip() or None
        expiry_date = _parse_expiry_date(item.get("expiry_date"))

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
        mrp_per_base_unit = convert_to_npr(mrp_original, mrp_currency)
        base_units = unit_row["qty_in_base_units"] * quantity
        computed_total += round(cost_price_per_base_unit * base_units, 2)
        prepared.append({
            "medicine_id": medicine_id, "unit_name": unit_name, "quantity": quantity,
            "cost_currency": cost_currency,
            "cost_price_original": cost_price_original,
            "cost_price_per_base_unit": cost_price_per_base_unit,
            "mrp_currency": mrp_currency,
            "mrp_original": mrp_original,
            "mrp_per_base_unit": mrp_per_base_unit,
            "max_discount_percent": max_discount_percent,
            "batch_number": batch_number,
            "expiry_date": expiry_date,
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
        _apply_stock_receipt(
            db, p["medicine_id"], p["unit_name"], p["quantity"],
            p["cost_price_per_base_unit"], p["mrp_per_base_unit"],
            purchase_bill_id=purchase_bill_id, cost_currency=p["cost_currency"],
            cost_price_original=round(p["cost_price_original"], 2),
            mrp_currency=p["mrp_currency"], mrp_original=round(p["mrp_original"], 2),
            batch_number=p["batch_number"], expiry_date=p["expiry_date"],
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


def list_purchase_bills(vendor_id=None, date_from=None, date_to=None):
    """List purchase bills, optionally scoped by vendor and/or a bill_date range.

    All three filters are optional and independent -- called with just a
    vendor_id (the existing vendor-detail-page call site) it behaves exactly
    as before; called with none of them, it's the cross-vendor Purchase Book.
    """
    db = get_db()
    query = """
        SELECT pb.*, v.name AS vendor_name, u.username AS recorded_by_username,
               COALESCE(payments.total_paid, 0) AS total_paid,
               pb.total_amount - COALESCE(payments.total_paid, 0) AS amount_due
        FROM purchase_bills pb
        JOIN vendors v ON v.id = pb.vendor_id
        JOIN users u ON u.id = pb.recorded_by_user_id
        LEFT JOIN (SELECT purchase_bill_id, SUM(amount) AS total_paid
                   FROM purchase_payments GROUP BY purchase_bill_id) payments
          ON payments.purchase_bill_id = pb.id
    """
    conditions = []
    params = []
    if vendor_id is not None:
        conditions.append("pb.vendor_id = ?")
        params.append(vendor_id)
    if date_from:
        conditions.append("pb.bill_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("pb.bill_date <= ?")
        params.append(date_to)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY pb.bill_date DESC, pb.id DESC"
    return db.execute(query, params).fetchall()


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


def list_stock_receipts_for_bill(purchase_bill_id):
    db = get_db()
    return db.execute(
        "SELECT sr.*, m.name AS medicine_name FROM stock_receipts sr "
        "JOIN medicines m ON m.id = sr.medicine_id WHERE sr.purchase_bill_id = ? ORDER BY sr.id",
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
            "company_name": m["company_name"],
            "cost_price_per_base_unit": m["cost_price_per_base_unit"],
            "mrp_per_base_unit": m["mrp_per_base_unit"],
            "units": [{"unit_name": u["unit_name"]} for u in units],
        })
    return results


# --- purchase returns -------------------------------------------------------

def returnable_quantity(purchase_bill_id, medicine_id, unit_name, batch_number=None):
    """How many units of this bill's medicine/unit line are still eligible to
    return -- what was received on this bill, minus what's already been
    returned (and not voided) against it.

    When batch_number is omitted, this aggregates across every batch of this
    medicine/unit on the bill -- the original, backward-compatible behavior.
    Passing batch_number scopes the received sum to that one batch, so two
    batches of the same medicine on one bill return independently of each
    other. The returned sum, however, must count BOTH prior returns that
    named that exact batch AND prior returns that were submitted unscoped
    (batch_number IS NULL) against the same medicine/unit on this bill --
    an unscoped return doesn't record which batch it actually came from, so
    it has to be conservatively counted against every batch's availability.
    Otherwise an unscoped return followed by a scoped return of the same
    goods would double-count what's still outstanding and allow an
    over-return.
    """
    db = get_db()
    if batch_number is not None:
        received = db.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS q FROM stock_receipts "
            "WHERE purchase_bill_id = ? AND medicine_id = ? AND unit_name = ? AND batch_number = ?",
            (purchase_bill_id, medicine_id, unit_name, batch_number),
        ).fetchone()["q"]
        returned = db.execute(
            "SELECT COALESCE(SUM(pri.quantity), 0) AS q FROM purchase_return_items pri "
            "JOIN purchase_returns pr ON pr.id = pri.purchase_return_id "
            "WHERE pr.purchase_bill_id = ? AND pri.medicine_id = ? AND pri.unit_name = ? "
            "AND (pri.batch_number = ? OR pri.batch_number IS NULL) AND pr.voided = 0",
            (purchase_bill_id, medicine_id, unit_name, batch_number),
        ).fetchone()["q"]
    else:
        received = db.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS q FROM stock_receipts "
            "WHERE purchase_bill_id = ? AND medicine_id = ? AND unit_name = ?",
            (purchase_bill_id, medicine_id, unit_name),
        ).fetchone()["q"]
        returned = db.execute(
            "SELECT COALESCE(SUM(pri.quantity), 0) AS q FROM purchase_return_items pri "
            "JOIN purchase_returns pr ON pr.id = pri.purchase_return_id "
            "WHERE pr.purchase_bill_id = ? AND pri.medicine_id = ? AND pri.unit_name = ? AND pr.voided = 0",
            (purchase_bill_id, medicine_id, unit_name),
        ).fetchone()["q"]
    return received - returned


def create_purchase_return(purchase_bill_id, items, reason, user_id):
    if not items:
        raise ValueError("purchase return must include at least one item")
    if reason not in RETURN_REASONS:
        raise ValueError(f"reason must be one of: {', '.join(RETURN_REASONS)}")

    db = get_db()
    bill = db.execute("SELECT * FROM purchase_bills WHERE id = ?", (purchase_bill_id,)).fetchone()
    if bill is None:
        raise ValueError(f"purchase bill {purchase_bill_id} not found")

    # --- validation pass ---
    prepared = []
    computed_total = 0.0
    # (medicine_id, unit_name, batch_number) -> cumulative requested qty scoped to
    # that exact batch (batch_number is not None here).
    requested_by_batch = {}
    # (medicine_id, unit_name) -> cumulative requested qty submitted unscoped
    # (batch_number is None) for that medicine/unit.
    requested_unscoped = {}
    for item in items:
        medicine_id = item["medicine_id"]
        unit_name = item["unit_name"]
        quantity = item["quantity"]
        batch_number = item.get("batch_number")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive whole number")

        unit_row = db.execute(
            "SELECT qty_in_base_units FROM medicine_units WHERE medicine_id = ? AND unit_name = ?",
            (medicine_id, unit_name),
        ).fetchone()
        if unit_row is None:
            raise ValueError(f"unknown unit '{unit_name}' for medicine {medicine_id}")

        # Sum requested quantities across every submitted item sharing the same
        # scope -- not just this row -- so multiple return rows for the same
        # line item can't each individually pass the returnable check while
        # their combined total exceeds it. An unscoped request and a
        # batch-scoped request for the same medicine/unit compete for the same
        # underlying receipt pool (mirroring returnable_quantity's own
        # cross-scope accounting above), so each is checked against the
        # combined total of same-scope requests plus opposite-scope requests
        # for that medicine/unit, not two independent pools.
        medicine_unit_key = (medicine_id, unit_name)
        if batch_number is None:
            requested_unscoped[medicine_unit_key] = requested_unscoped.get(medicine_unit_key, 0) + quantity
            combined_requested = requested_unscoped[medicine_unit_key] + sum(
                qty for (m_id, u_name, _batch), qty in requested_by_batch.items()
                if (m_id, u_name) == medicine_unit_key
            )
        else:
            batch_key = (medicine_id, unit_name, batch_number)
            requested_by_batch[batch_key] = requested_by_batch.get(batch_key, 0) + quantity
            combined_requested = requested_by_batch[batch_key] + requested_unscoped.get(medicine_unit_key, 0)

        max_returnable = returnable_quantity(purchase_bill_id, medicine_id, unit_name, batch_number=batch_number)
        if combined_requested > max_returnable:
            raise ValueError(f"cannot return more than {max_returnable} of this item on this bill")

        medicine = db.execute("SELECT * FROM medicines WHERE id = ?", (medicine_id,)).fetchone()
        base_units = unit_row["qty_in_base_units"] * quantity
        if medicine["stock_in_base_units"] < base_units:
            raise ValueError(f"cannot return more {medicine['name']} than is currently in stock")

        if batch_number is not None:
            cost_row = db.execute(
                "SELECT cost_price_per_base_unit FROM stock_receipts "
                "WHERE purchase_bill_id = ? AND medicine_id = ? AND unit_name = ? AND batch_number = ? "
                "ORDER BY id DESC LIMIT 1",
                (purchase_bill_id, medicine_id, unit_name, batch_number),
            ).fetchone()
        else:
            cost_row = db.execute(
                "SELECT cost_price_per_base_unit FROM stock_receipts "
                "WHERE purchase_bill_id = ? AND medicine_id = ? AND unit_name = ? "
                "ORDER BY id DESC LIMIT 1",
                (purchase_bill_id, medicine_id, unit_name),
            ).fetchone()
        cost_price_per_base_unit = cost_row["cost_price_per_base_unit"]
        amount = round(cost_price_per_base_unit * base_units, 2)
        computed_total += amount
        prepared.append({
            "medicine_id": medicine_id, "unit_name": unit_name, "quantity": quantity,
            "qty_in_base_units": unit_row["qty_in_base_units"], "base_units": base_units,
            "cost_price_per_base_unit": cost_price_per_base_unit, "amount": amount,
            "batch_number": batch_number,
        })

    total_amount = round(computed_total, 2)

    # --- write pass ---
    cur = db.execute(
        "INSERT INTO purchase_returns (purchase_bill_id, return_date, reason, total_amount, "
        "recorded_by_user_id, voided) VALUES (?, date('now', 'localtime'), ?, ?, ?, 0)",
        (purchase_bill_id, reason, total_amount, user_id),
    )
    return_id = cur.lastrowid
    for p in prepared:
        db.execute(
            "INSERT INTO purchase_return_items (purchase_return_id, medicine_id, unit_name, quantity, "
            "qty_in_base_units, base_units_returned, cost_price_per_base_unit, amount, batch_number) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (return_id, p["medicine_id"], p["unit_name"], p["quantity"], p["qty_in_base_units"],
             p["base_units"], p["cost_price_per_base_unit"], p["amount"], p["batch_number"]),
        )
        db.execute(
            "UPDATE medicines SET stock_in_base_units = stock_in_base_units - ? WHERE id = ?",
            (p["base_units"], p["medicine_id"]),
        )
    db.execute(
        "UPDATE purchase_bills SET total_amount = total_amount - ? WHERE id = ?",
        (total_amount, purchase_bill_id),
    )
    db.commit()
    return {"purchase_return_id": return_id, "total_amount": total_amount}


def void_purchase_return(return_id):
    db = get_db()
    ret = db.execute("SELECT * FROM purchase_returns WHERE id = ?", (return_id,)).fetchone()
    if ret is None:
        raise ValueError(f"purchase return {return_id} not found")
    if ret["voided"]:
        raise ValueError(f"purchase return {return_id} already voided")

    items = db.execute(
        "SELECT * FROM purchase_return_items WHERE purchase_return_id = ?", (return_id,)
    ).fetchall()
    for item in items:
        db.execute(
            "UPDATE medicines SET stock_in_base_units = stock_in_base_units + ? WHERE id = ?",
            (item["base_units_returned"], item["medicine_id"]),
        )
    db.execute(
        "UPDATE purchase_bills SET total_amount = total_amount + ? WHERE id = ?",
        (ret["total_amount"], ret["purchase_bill_id"]),
    )
    db.execute("UPDATE purchase_returns SET voided = 1 WHERE id = ?", (return_id,))
    db.commit()


def list_purchase_returns(purchase_bill_id):
    db = get_db()
    returns = db.execute(
        "SELECT * FROM purchase_returns WHERE purchase_bill_id = ? ORDER BY id DESC",
        (purchase_bill_id,),
    ).fetchall()
    result = []
    for r in returns:
        items = db.execute(
            "SELECT pri.*, m.name AS medicine_name FROM purchase_return_items pri "
            "JOIN medicines m ON m.id = pri.medicine_id WHERE pri.purchase_return_id = ?",
            (r["id"],),
        ).fetchall()
        result.append({"return": r, "items": items})
    return result


@bp.route("", methods=["GET"])
@role_required("admin")
def purchase_book_view():
    from vendors import list_vendors

    vendor_id = request.args.get("vendor_id", type=int)
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    bills = list_purchase_bills(vendor_id=vendor_id, date_from=date_from, date_to=date_to)
    return render_template(
        "purchase_book.html", bills=bills, vendors=list_vendors(),
        vendor_id=vendor_id, date_from=date_from, date_to=date_to,
    )


@bp.route("/new")
@role_required("admin")
def new_purchase_bill_view():
    from vendors import get_vendor

    preselected_vendor_id = request.args.get("vendor_id", type=int)
    preselected_vendor = get_vendor(preselected_vendor_id) if preselected_vendor_id else None
    return render_template("purchase_bill_new.html", preselected_vendor=preselected_vendor)


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
        stock_receipts=list_stock_receipts_for_bill(purchase_bill_id),
        payments=list_payments(purchase_bill_id),
        returns=list_purchase_returns(purchase_bill_id),
        total_paid=bill_total_paid(purchase_bill_id),
        amount_due=bill_amount_due(purchase_bill_id),
    )


@bp.route("/<int:purchase_bill_id>/report")
@role_required("admin")
def purchase_report_view(purchase_bill_id):
    bill = get_purchase_bill(purchase_bill_id)
    if bill is None:
        return "Purchase bill not found", 404
    return render_template(
        "purchase_report.html", bill=bill,
        stock_receipts=list_stock_receipts_for_bill(purchase_bill_id),
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


@bp.route("/<int:purchase_bill_id>/returnable")
@role_required("admin")
def returnable_quantity_view(purchase_bill_id):
    medicine_id = request.args.get("medicine_id", type=int)
    unit_name = request.args.get("unit_name", "")
    batch_number = request.args.get("batch_number") or None
    return jsonify({
        "returnable": returnable_quantity(purchase_bill_id, medicine_id, unit_name, batch_number=batch_number)
    })


@bp.route("/<int:purchase_bill_id>/returns", methods=["POST"])
@role_required("admin")
def create_purchase_return_view(purchase_bill_id):
    user = current_user()
    try:
        payload = request.get_json()
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("return must include at least one item")
        reason = payload.get("reason") or "other"
        result = create_purchase_return(purchase_bill_id, items, reason, user["id"])
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@bp.route("/returns/<int:return_id>/void", methods=["POST"])
@role_required("admin")
def void_purchase_return_view(return_id):
    db = get_db()
    ret = db.execute("SELECT purchase_bill_id FROM purchase_returns WHERE id = ?", (return_id,)).fetchone()
    if ret is None:
        return "Purchase return not found", 404
    try:
        void_purchase_return(return_id)
    except ValueError as e:
        flash(str(e))
    return redirect(url_for("purchases.purchase_bill_detail_view", purchase_bill_id=ret["purchase_bill_id"]))
