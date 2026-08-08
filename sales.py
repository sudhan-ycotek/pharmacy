from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from auth import current_user, login_required, role_required
from db import get_db
from inventory import get_medicine_units, search_medicines

bp = Blueprint("sales", __name__, url_prefix="/sales")


def create_sale(user_id, items):
    if not items:
        raise ValueError("sale must include at least one item")

    db = get_db()
    prepared = []
    total = 0.0
    # Track cumulative demand per medicine_id to prevent overselling across duplicate line items
    cumulative_demand = {}

    for item in items:
        try:
            medicine_id = item["medicine_id"]
            unit_name = item["unit_name"]
            quantity = item["quantity"]
        except (KeyError, TypeError) as e:
            raise ValueError(f"invalid item structure: {e}")

        try:
            if quantity <= 0:
                raise ValueError("quantity must be positive")
        except TypeError:
            raise ValueError("quantity must be a positive number")

        unit_row = db.execute(
            "SELECT qty_in_base_units, price FROM medicine_units "
            "WHERE medicine_id = ? AND unit_name = ?",
            (medicine_id, unit_name),
        ).fetchone()
        if unit_row is None:
            raise ValueError(f"unknown unit '{unit_name}' for medicine {medicine_id}")

        medicine_row = db.execute(
            "SELECT stock_in_base_units FROM medicines WHERE id = ?", (medicine_id,)
        ).fetchone()
        if medicine_row is None:
            raise ValueError(f"medicine {medicine_id} not found")

        base_units_needed = unit_row["qty_in_base_units"] * quantity

        # Check cumulative demand (including previous items for the same medicine)
        if medicine_id not in cumulative_demand:
            cumulative_demand[medicine_id] = 0
        cumulative_demand[medicine_id] += base_units_needed

        if medicine_row["stock_in_base_units"] < cumulative_demand[medicine_id]:
            raise ValueError(f"insufficient stock for medicine {medicine_id}")

        subtotal = round(unit_row["price"] * quantity, 2)
        total += subtotal
        prepared.append((medicine_id, unit_name, quantity, unit_row["price"], subtotal, base_units_needed))

    total = round(total, 2)
    cur = db.execute(
        "INSERT INTO sales (user_id, timestamp, total, voided) VALUES (?, datetime('now'), ?, 0)",
        (user_id, total),
    )
    sale_id = cur.lastrowid
    for medicine_id, unit_name, quantity, price, subtotal, base_units_needed in prepared:
        db.execute(
            "INSERT INTO sale_items (sale_id, medicine_id, unit_name, quantity, unit_price, subtotal) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sale_id, medicine_id, unit_name, quantity, price, subtotal),
        )
        db.execute(
            "UPDATE medicines SET stock_in_base_units = stock_in_base_units - ? WHERE id = ?",
            (base_units_needed, medicine_id),
        )
    db.commit()
    return {"sale_id": sale_id, "total": total}


def void_sale(sale_id):
    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if sale is None:
        raise ValueError(f"sale {sale_id} not found")
    if sale["voided"]:
        raise ValueError(f"sale {sale_id} already voided")

    items = db.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
    for item in items:
        unit_row = db.execute(
            "SELECT qty_in_base_units FROM medicine_units WHERE medicine_id = ? AND unit_name = ?",
            (item["medicine_id"], item["unit_name"]),
        ).fetchone()
        base_units = unit_row["qty_in_base_units"] * item["quantity"]
        db.execute(
            "UPDATE medicines SET stock_in_base_units = stock_in_base_units + ? WHERE id = ?",
            (base_units, item["medicine_id"]),
        )
    db.execute("UPDATE sales SET voided = 1 WHERE id = ?", (sale_id,))
    db.commit()


def today_sales_total():
    db = get_db()
    row = db.execute(
        "SELECT COALESCE(SUM(total), 0) AS total FROM sales "
        "WHERE voided = 0 AND date(timestamp) = date('now')"
    ).fetchone()
    return row["total"]


def get_sale(sale_id):
    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if sale is None:
        return None
    items = db.execute(
        "SELECT si.*, m.name AS medicine_name FROM sale_items si "
        "JOIN medicines m ON m.id = si.medicine_id WHERE si.sale_id = ?",
        (sale_id,),
    ).fetchall()
    return {"sale": sale, "items": items}


@bp.route("/new")
@login_required
def new_sale():
    return render_template("new_sale.html")


@bp.route("/search")
@login_required
def search():
    query = request.args.get("q", "")
    medicines = search_medicines(query)
    results = []
    for m in medicines:
        units = get_medicine_units(m["id"])
        results.append({
            "id": m["id"],
            "name": m["name"],
            "units": [{"unit_name": u["unit_name"], "price": u["price"]} for u in units],
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

        result = create_sale(user["id"], items)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@bp.route("/<int:sale_id>/receipt")
@login_required
def receipt(sale_id):
    sale = get_sale(sale_id)
    if sale is None:
        return "Sale not found", 404
    return render_template("receipt.html", sale=sale["sale"], items=sale["items"])


@bp.route("/<int:sale_id>/void", methods=["POST"])
@role_required("admin")
def void(sale_id):
    try:
        void_sale(sale_id)
    except ValueError as e:
        return str(e), 400
    return redirect(url_for("sales.receipt", sale_id=sale_id))
