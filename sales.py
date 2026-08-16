from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from auth import current_user, login_required, role_required
from db import get_db
from inventory import search_medicines, sellable_units

bp = Blueprint("sales", __name__, url_prefix="/sales")

SALE_RETURN_REASONS = ("wrong_item", "customer_request", "adverse_reaction", "other")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def create_sale(user_id, items, discount_mode="none", bill_discount_percent=0, patient_name=None,
                 doctor_name=None, payment_method="cash", tender_amount=None):
    if not items:
        raise ValueError("sale must include at least one item")
    if discount_mode not in ("none", "item", "bill"):
        raise ValueError("discount_mode must be 'none', 'item', or 'bill'")
    if not _is_number(bill_discount_percent):
        raise ValueError("bill_discount_percent must be a number")
    if discount_mode != "bill" and bill_discount_percent != 0:
        raise ValueError("bill_discount_percent must be 0 unless discount_mode is 'bill'")
    if payment_method not in ("cash", "online"):
        raise ValueError("payment_method must be 'cash' or 'online'")
    if tender_amount is not None:
        if not _is_number(tender_amount):
            raise ValueError("tender_amount must be a number")
        if payment_method != "cash":
            raise ValueError("tender_amount must not be given unless payment_method is 'cash'")

    db = get_db()
    prepared = []
    # Track cumulative demand per medicine_id to prevent overselling across
    # duplicate line items of the same medicine (e.g. a Tablet line and a File
    # line both drawing from the same medicine's stock_in_base_units).
    cumulative_demand = {}
    medicine_max_discounts = {}

    for item in items:
        try:
            medicine_id = item["medicine_id"]
            unit_name = item["unit_name"]
            quantity = item["quantity"]
        except (KeyError, TypeError) as e:
            raise ValueError(f"invalid item structure: {e}")
        item_discount_percent = item.get("discount_percent", 0)

        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ValueError("quantity must be a whole number")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if not _is_number(item_discount_percent):
            raise ValueError("discount_percent must be a number")
        if discount_mode != "item" and item_discount_percent != 0:
            raise ValueError("per-item discount_percent must be 0 unless discount_mode is 'item'")

        medicine_row = db.execute("SELECT * FROM medicines WHERE id = ?", (medicine_id,)).fetchone()
        if medicine_row is None:
            raise ValueError(f"medicine {medicine_id} not found")
        medicine_max_discounts[medicine_id] = medicine_row["max_discount_percent"]

        unit_row = db.execute(
            "SELECT qty_in_base_units FROM medicine_units "
            "WHERE medicine_id = ? AND unit_name = ? AND is_sellable = 1",
            (medicine_id, unit_name),
        ).fetchone()
        if unit_row is None:
            raise ValueError(f"unknown unit '{unit_name}' for {medicine_row['name']}")

        if discount_mode == "item" and not (0 <= item_discount_percent <= medicine_row["max_discount_percent"]):
            raise ValueError(
                f"discount for {medicine_row['name']} cannot exceed {medicine_row['max_discount_percent']}%"
            )

        base_units_needed = unit_row["qty_in_base_units"] * quantity
        cumulative_demand[medicine_id] = cumulative_demand.get(medicine_id, 0) + base_units_needed
        if medicine_row["stock_in_base_units"] < cumulative_demand[medicine_id]:
            raise ValueError(f"Not enough {medicine_row['name']} in stock")

        gross_unit_price = round(medicine_row["mrp_per_base_unit"] * unit_row["qty_in_base_units"], 2)
        prepared.append({
            "medicine_id": medicine_id, "unit_name": unit_name,
            "qty_in_base_units": unit_row["qty_in_base_units"], "quantity": quantity,
            "cost_price_per_base_unit": medicine_row["cost_price_per_base_unit"],
            "mrp_per_base_unit": medicine_row["mrp_per_base_unit"], "gross_unit_price": gross_unit_price,
            "item_discount_percent": item_discount_percent, "base_units_needed": base_units_needed,
        })

    if discount_mode == "bill":
        applicable_cap = min(medicine_max_discounts.values())
        if not (0 <= bill_discount_percent <= applicable_cap):
            raise ValueError(
                f"bill discount cannot exceed {applicable_cap}% (lowest max discount among items in this bill)"
            )
        for p in prepared:
            p["item_discount_percent"] = bill_discount_percent

    total = 0.0
    subtotal_before_discount = 0.0
    for p in prepared:
        p["unit_price"] = round(p["gross_unit_price"] * (1 - p["item_discount_percent"] / 100), 2)
        p["subtotal"] = round(p["unit_price"] * p["quantity"], 2)
        subtotal_before_discount += round(p["gross_unit_price"] * p["quantity"], 2)
        total += p["subtotal"]

    total = round(total, 2)
    subtotal_before_discount = round(subtotal_before_discount, 2)
    discount_amount = round(subtotal_before_discount - total, 2)

    if payment_method == "cash":
        if tender_amount is None:
            # No tender given: treat as tendered exactly the total (zero change). This
            # keeps existing direct create_sale(...) call sites working unmodified.
            change_amount = 0.0
        else:
            if tender_amount < total:
                raise ValueError(f"tender_amount must not be less than the total (Rs {total:.2f})")
            change_amount = round(tender_amount - total, 2)
    else:
        change_amount = None

    cur = db.execute(
        "INSERT INTO sales (user_id, timestamp, patient_name, subtotal_before_discount, discount_mode, "
        "bill_discount_percent, discount_amount, total, voided, doctor_name, payment_method, "
        "tender_amount, change_amount) "
        "VALUES (?, datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
        (user_id, patient_name, subtotal_before_discount, discount_mode, bill_discount_percent,
         discount_amount, total, doctor_name, payment_method, tender_amount, change_amount),
    )
    sale_id = cur.lastrowid
    for p in prepared:
        db.execute(
            "INSERT INTO sale_items (sale_id, medicine_id, unit_name, qty_in_base_units, "
            "quantity, cost_price_per_base_unit, mrp_per_base_unit, gross_unit_price, "
            "discount_percent, unit_price, subtotal) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sale_id, p["medicine_id"], p["unit_name"], p["qty_in_base_units"], p["quantity"],
             p["cost_price_per_base_unit"], p["mrp_per_base_unit"], p["gross_unit_price"],
             p["item_discount_percent"], p["unit_price"], p["subtotal"]),
        )
        db.execute(
            "UPDATE medicines SET stock_in_base_units = stock_in_base_units - ? WHERE id = ?",
            (p["base_units_needed"], p["medicine_id"]),
        )
    db.commit()
    return {"sale_id": sale_id, "total": total, "discount_amount": discount_amount,
            "subtotal_before_discount": subtotal_before_discount, "change_amount": change_amount}


def void_sale(sale_id):
    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if sale is None:
        raise ValueError(f"sale {sale_id} not found")
    if sale["voided"]:
        raise ValueError(f"sale {sale_id} already voided")
    active_returns = db.execute(
        "SELECT COUNT(*) AS c FROM sale_returns WHERE sale_id = ? AND voided = 0", (sale_id,)
    ).fetchone()["c"]
    if active_returns:
        raise ValueError(
            f"cannot void sale {sale_id}: it has active sale returns against it -- "
            "void those returns first"
        )

    items = db.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
    for item in items:
        base_units = item["qty_in_base_units"] * item["quantity"]
        db.execute(
            "UPDATE medicines SET stock_in_base_units = stock_in_base_units + ? WHERE id = ?",
            (base_units, item["medicine_id"]),
        )
    db.execute("UPDATE sales SET voided = 1 WHERE id = ?", (sale_id,))
    db.commit()


def daily_sales_totals(days=7):
    db = get_db()
    return db.execute(
        """
        SELECT date(s.timestamp) AS day,
               COALESCE(SUM(s.total), 0) AS revenue,
               COALESCE(SUM(si.qty), 0) AS items_sold,
               COALESCE(SUM(si.profit), 0) AS profit
        FROM sales s
        LEFT JOIN (
            SELECT sale_id,
                   SUM(qty_in_base_units * quantity) AS qty,
                   SUM(subtotal - cost_price_per_base_unit * qty_in_base_units * quantity) AS profit
            FROM sale_items GROUP BY sale_id
        ) si ON si.sale_id = s.id
        WHERE s.voided = 0 AND date(s.timestamp) >= date('now', 'localtime', ?)
        GROUP BY day
        """,
        (f"-{days} days",),
    ).fetchall()


def today_sales_total():
    db = get_db()
    row = db.execute(
        "SELECT COALESCE(SUM(total), 0) AS total FROM sales "
        "WHERE voided = 0 AND date(timestamp) = date('now', 'localtime')"
    ).fetchone()
    return row["total"]


def get_sale(sale_id):
    db = get_db()
    sale = db.execute(
        "SELECT s.*, u.username FROM sales s JOIN users u ON u.id = s.user_id WHERE s.id = ?",
        (sale_id,),
    ).fetchone()
    if sale is None:
        return None
    items = db.execute(
        "SELECT si.*, m.name AS medicine_name, "
        "(si.subtotal - si.cost_price_per_base_unit * si.qty_in_base_units * si.quantity) AS profit "
        "FROM sale_items si "
        "JOIN medicines m ON m.id = si.medicine_id "
        "WHERE si.sale_id = ?",
        (sale_id,),
    ).fetchall()
    return {"sale": sale, "items": items}


def list_sales(user_id=None):
    db = get_db()
    base_query = """
        SELECT s.*, u.username, COALESCE(profit.total_profit, 0) AS profit
        FROM sales s
        JOIN users u ON u.id = s.user_id
        LEFT JOIN (
            SELECT sale_id,
                   SUM(subtotal - cost_price_per_base_unit * qty_in_base_units * quantity) AS total_profit
            FROM sale_items GROUP BY sale_id
        ) profit ON profit.sale_id = s.id
    """
    if user_id is None:
        return db.execute(base_query + " ORDER BY s.id DESC LIMIT 50").fetchall()
    return db.execute(
        base_query + " WHERE s.user_id = ? ORDER BY s.id DESC LIMIT 50", (user_id,)
    ).fetchall()


def sales_register(date_from=None, date_to=None, search=None):
    """Sales Register: every sale (voided or not) across the whole shop, optionally
    scoped by a timestamp date range and/or a patient/doctor/username search term,
    with each row's already-returned amount netted out via a joined subquery --
    sales.total itself is never mutated by a return, so this is the only place
    that number is adjusted for display.
    """
    db = get_db()
    query = """
        SELECT s.*, u.username,
               COALESCE(returns.total_returned, 0) AS returned_amount,
               s.total - COALESCE(returns.total_returned, 0) AS net_total
        FROM sales s
        JOIN users u ON u.id = s.user_id
        LEFT JOIN (
            SELECT sale_id, SUM(total_amount) AS total_returned
            FROM sale_returns WHERE voided = 0 GROUP BY sale_id
        ) returns ON returns.sale_id = s.id
    """
    conditions = []
    params = []
    if date_from:
        conditions.append("date(s.timestamp) >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("date(s.timestamp) <= ?")
        params.append(date_to)
    if search:
        conditions.append("(s.patient_name LIKE ? OR s.doctor_name LIKE ? OR u.username LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY s.id DESC"
    return db.execute(query, params).fetchall()


# --- sale returns ------------------------------------------------------------

def returnable_sale_item_quantity(sale_item_id):
    """How many units of this specific sale line item are still eligible to
    return -- what was sold on this line, minus what's already been returned
    (and not voided) against it.

    Scoped by sale_item_id rather than (medicine_id, unit_name) because a sale
    can legitimately contain two line items for the same medicine+unit sold at
    different per-item discounted prices -- each line's returnable quantity
    must be tracked independently of the other.
    """
    db = get_db()
    item = db.execute("SELECT * FROM sale_items WHERE id = ?", (sale_item_id,)).fetchone()
    if item is None:
        raise ValueError(f"sale item {sale_item_id} not found")
    returned = db.execute(
        "SELECT COALESCE(SUM(sri.quantity), 0) AS q FROM sale_return_items sri "
        "JOIN sale_returns sr ON sr.id = sri.sale_return_id "
        "WHERE sri.sale_item_id = ? AND sr.voided = 0",
        (sale_item_id,),
    ).fetchone()["q"]
    return item["quantity"] - returned


def create_sale_return(sale_id, items, reason, user_id):
    if not items:
        raise ValueError("sale return must include at least one item")
    if reason not in SALE_RETURN_REASONS:
        raise ValueError(f"reason must be one of: {', '.join(SALE_RETURN_REASONS)}")

    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if sale is None:
        raise ValueError(f"sale {sale_id} not found")
    if sale["voided"]:
        raise ValueError(f"cannot return items from voided sale {sale_id}")

    # --- validation pass: nothing is written until every item is confirmed valid ---
    prepared = []
    computed_total = 0.0
    requested_totals = {}  # sale_item_id -> cumulative requested qty across this call
    for item in items:
        try:
            sale_item_id = item["sale_item_id"]
            quantity = item["quantity"]
        except (KeyError, TypeError) as e:
            raise ValueError(f"invalid item structure: {e}")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive whole number")

        sale_item = db.execute("SELECT * FROM sale_items WHERE id = ?", (sale_item_id,)).fetchone()
        if sale_item is None:
            raise ValueError(f"sale item {sale_item_id} not found")
        if sale_item["sale_id"] != sale_id:
            raise ValueError(f"sale item {sale_item_id} does not belong to sale {sale_id}")

        # Sum requested quantities across every submitted item sharing this same
        # sale_item_id -- not just this row -- so two return rows for the same
        # line item can't each individually pass the returnable check while their
        # combined total exceeds it.
        requested_totals[sale_item_id] = requested_totals.get(sale_item_id, 0) + quantity
        max_returnable = returnable_sale_item_quantity(sale_item_id)
        if requested_totals[sale_item_id] > max_returnable:
            raise ValueError(f"cannot return more than {max_returnable} of this item on this sale")

        base_units = sale_item["qty_in_base_units"] * quantity
        amount = round(sale_item["unit_price"] * quantity, 2)
        computed_total += amount
        prepared.append({
            "sale_item_id": sale_item_id, "medicine_id": sale_item["medicine_id"],
            "unit_name": sale_item["unit_name"], "quantity": quantity,
            "qty_in_base_units": sale_item["qty_in_base_units"], "base_units": base_units,
            "unit_price": sale_item["unit_price"], "amount": amount,
        })

    total_amount = round(computed_total, 2)

    # --- write pass ---
    cur = db.execute(
        "INSERT INTO sale_returns (sale_id, return_date, reason, total_amount, "
        "recorded_by_user_id, voided) VALUES (?, date('now', 'localtime'), ?, ?, ?, 0)",
        (sale_id, reason, total_amount, user_id),
    )
    return_id = cur.lastrowid
    for p in prepared:
        db.execute(
            "INSERT INTO sale_return_items (sale_return_id, sale_item_id, medicine_id, unit_name, "
            "quantity, qty_in_base_units, base_units_returned, unit_price, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (return_id, p["sale_item_id"], p["medicine_id"], p["unit_name"], p["quantity"],
             p["qty_in_base_units"], p["base_units"], p["unit_price"], p["amount"]),
        )
        db.execute(
            "UPDATE medicines SET stock_in_base_units = stock_in_base_units + ? WHERE id = ?",
            (p["base_units"], p["medicine_id"]),
        )
    # Note: sales.total is never mutated here -- the Sales Register nets out
    # returned amounts via a joined subquery instead (see sales_register()).
    db.commit()
    return {"sale_return_id": return_id, "total_amount": total_amount}


def void_sale_return(return_id):
    db = get_db()
    ret = db.execute("SELECT * FROM sale_returns WHERE id = ?", (return_id,)).fetchone()
    if ret is None:
        raise ValueError(f"sale return {return_id} not found")
    if ret["voided"]:
        raise ValueError(f"sale return {return_id} already voided")

    items = db.execute(
        "SELECT * FROM sale_return_items WHERE sale_return_id = ?", (return_id,)
    ).fetchall()

    # Aggregate base units to remove per medicine (a single return can include more
    # than one line item for the same medicine), then validate every medicine
    # currently holds enough stock before mutating anything -- voiding a return
    # must undo the restock, but the restocked units may since have been resold
    # or adjusted away, which would otherwise drive stock negative.
    needed_by_medicine = {}
    for item in items:
        needed_by_medicine[item["medicine_id"]] = (
            needed_by_medicine.get(item["medicine_id"], 0) + item["base_units_returned"]
        )

    for medicine_id, needed in needed_by_medicine.items():
        medicine = db.execute("SELECT * FROM medicines WHERE id = ?", (medicine_id,)).fetchone()
        if medicine["stock_in_base_units"] < needed:
            raise ValueError(
                f"cannot void return: not enough {medicine['name']} currently in stock "
                "(some may have been resold or adjusted since the return)"
            )

    for medicine_id, needed in needed_by_medicine.items():
        db.execute(
            "UPDATE medicines SET stock_in_base_units = stock_in_base_units - ? WHERE id = ?",
            (needed, medicine_id),
        )
    db.execute("UPDATE sale_returns SET voided = 1 WHERE id = ?", (return_id,))
    db.commit()


def list_sale_returns(sale_id):
    db = get_db()
    returns = db.execute(
        "SELECT * FROM sale_returns WHERE sale_id = ? ORDER BY id DESC",
        (sale_id,),
    ).fetchall()
    result = []
    for r in returns:
        items = db.execute(
            "SELECT sri.*, m.name AS medicine_name FROM sale_return_items sri "
            "JOIN medicines m ON m.id = sri.medicine_id WHERE sri.sale_return_id = ?",
            (r["id"],),
        ).fetchall()
        result.append({"return": r, "items": items})
    return result


@bp.route("/new")
@login_required
def new_sale():
    return render_template("new_sale.html")


@bp.route("")
@login_required
def list_sales_view():
    user = current_user()
    if user["role"] == "admin":
        sales = list_sales()
    else:
        sales = list_sales(user_id=user["id"])
    return render_template("sales_list.html", sales=sales)


@bp.route("/search")
@login_required
def search():
    query = request.args.get("q", "")
    medicines = search_medicines(query)
    results = []
    for m in medicines:
        units = sellable_units(m["id"])
        priced = m["mrp_per_base_unit"] > 0
        results.append({
            "id": m["id"], "name": m["name"], "packaging_type": m["packaging_type"],
            "photo_path": m["photo_path"], "max_discount_percent": m["max_discount_percent"],
            "units": [
                {
                    "unit_name": u["unit_name"],
                    "price": round(m["mrp_per_base_unit"] * u["qty_in_base_units"], 2) if priced else None,
                }
                for u in units
            ],
        })
    return jsonify(results)


@bp.route("/register")
@role_required("admin")
def sales_register_view():
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    search_term = request.args.get("q") or None
    sales = sales_register(date_from=date_from, date_to=date_to, search=search_term)
    totals = {
        "gross": sum(s["total"] for s in sales),
        "returned": sum(s["returned_amount"] for s in sales),
        "net": sum(s["net_total"] for s in sales),
    }
    return render_template(
        "sales_register.html", sales=sales, date_from=date_from, date_to=date_to,
        search=search_term, totals=totals,
    )


@bp.route("/returns")
@role_required("admin")
def sale_returns_lookup_view():
    return render_template("sales_return.html")


@bp.route("/returns/search")
@role_required("admin")
def sale_returns_search_view():
    query = request.args.get("q", "")
    db = get_db()
    if not query.strip():
        rows = []
    else:
        rows = db.execute(
            "SELECT s.id, s.timestamp, s.patient_name, s.doctor_name, s.total, u.username "
            "FROM sales s JOIN users u ON u.id = s.user_id "
            "WHERE s.voided = 0 AND s.patient_name LIKE ? "
            "ORDER BY s.id DESC LIMIT 20",
            (f"%{query}%",),
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("", methods=["POST"])
@login_required
def finalize():
    payload = request.get_json()
    user = current_user()
    try:
        # Validate payload structure
        if payload is None:
            raise ValueError("request body must be JSON")
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        if "items" not in payload:
            raise ValueError("request must include 'items' field")
        items = payload["items"]
        if not isinstance(items, list):
            raise ValueError("'items' must be a list")
        if not items:
            raise ValueError("sale must include at least one item")

        patient_name = (payload.get("patient_name") or "").strip() or None
        doctor_name = (payload.get("doctor_name") or "").strip() or None
        payment_method = payload.get("payment_method", "cash")
        tender_amount = payload.get("tender_amount")
        # Stricter than create_sale's library default: a cash payment coming through the
        # actual POS UI must always include an explicit tender_amount. This keeps the
        # permissive create_sale default (omitted tender => zero change) from masking a
        # real missing-tender bug in the finalize flow.
        if payment_method == "cash" and tender_amount is None:
            raise ValueError("tender_amount is required for cash payments")
        result = create_sale(
            user["id"], items,
            discount_mode=payload.get("discount_mode", "none"),
            bill_discount_percent=payload.get("bill_discount_percent", 0),
            patient_name=patient_name,
            doctor_name=doctor_name,
            payment_method=payment_method,
            tender_amount=tender_amount,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@bp.route("/<int:sale_id>/receipt")
@login_required
def receipt(sale_id):
    sale = get_sale(sale_id)
    if sale is None:
        return "Sale not found", 404
    user = current_user()
    if user["role"] != "admin" and sale["sale"]["user_id"] != user["id"]:
        abort(403)
    total_profit = sum(i["profit"] for i in sale["items"])
    return render_template(
        "receipt.html", sale=sale["sale"], items=sale["items"], total_profit=total_profit,
        returns=list_sale_returns(sale_id),
    )


@bp.route("/<int:sale_id>/void", methods=["POST"])
@role_required("admin")
def void(sale_id):
    try:
        void_sale(sale_id)
    except ValueError as e:
        return str(e), 400
    return redirect(url_for("sales.receipt", sale_id=sale_id))


@bp.route("/<int:sale_id>/items/<int:item_id>/returnable")
@role_required("admin")
def sale_item_returnable_view(sale_id, item_id):
    db = get_db()
    item = db.execute("SELECT * FROM sale_items WHERE id = ? AND sale_id = ?", (item_id, sale_id)).fetchone()
    if item is None:
        return "Sale item not found", 404
    return jsonify({"returnable": returnable_sale_item_quantity(item_id)})


@bp.route("/<int:sale_id>/returns", methods=["POST"])
@role_required("admin")
def create_sale_return_view(sale_id):
    user = current_user()
    try:
        payload = request.get_json()
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("return must include at least one item")
        reason = payload.get("reason") or "other"
        result = create_sale_return(sale_id, items, reason, user["id"])
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@bp.route("/returns/<int:return_id>/void", methods=["POST"])
@role_required("admin")
def void_sale_return_view(return_id):
    db = get_db()
    ret = db.execute("SELECT sale_id FROM sale_returns WHERE id = ?", (return_id,)).fetchone()
    if ret is None:
        return "Sale return not found", 404
    try:
        void_sale_return(return_id)
    except ValueError as e:
        flash(str(e))
    return redirect(url_for("sales.receipt", sale_id=ret["sale_id"]))
