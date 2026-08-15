from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from auth import current_user, login_required, role_required
from db import get_db
from inventory import search_medicines, sellable_units

bp = Blueprint("sales", __name__, url_prefix="/sales")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def create_sale(user_id, items, discount_mode="none", bill_discount_percent=0, patient_name=None):
    if not items:
        raise ValueError("sale must include at least one item")
    if discount_mode not in ("none", "item", "bill"):
        raise ValueError("discount_mode must be 'none', 'item', or 'bill'")
    if not _is_number(bill_discount_percent):
        raise ValueError("bill_discount_percent must be a number")
    if discount_mode != "bill" and bill_discount_percent != 0:
        raise ValueError("bill_discount_percent must be 0 unless discount_mode is 'bill'")

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

    cur = db.execute(
        "INSERT INTO sales (user_id, timestamp, patient_name, subtotal_before_discount, discount_mode, "
        "bill_discount_percent, discount_amount, total, voided) "
        "VALUES (?, datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?, 0)",
        (user_id, patient_name, subtotal_before_discount, discount_mode, bill_discount_percent,
         discount_amount, total),
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
            "subtotal_before_discount": subtotal_before_discount}


def void_sale(sale_id):
    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if sale is None:
        raise ValueError(f"sale {sale_id} not found")
    if sale["voided"]:
        raise ValueError(f"sale {sale_id} already voided")

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
        result = create_sale(
            user["id"], items,
            discount_mode=payload.get("discount_mode", "none"),
            bill_discount_percent=payload.get("bill_discount_percent", 0),
            patient_name=patient_name,
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
    return render_template("receipt.html", sale=sale["sale"], items=sale["items"], total_profit=total_profit)


@bp.route("/<int:sale_id>/void", methods=["POST"])
@role_required("admin")
def void(sale_id):
    try:
        void_sale(sale_id)
    except ValueError as e:
        return str(e), 400
    return redirect(url_for("sales.receipt", sale_id=sale_id))
