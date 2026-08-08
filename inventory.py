from flask import Blueprint, flash, redirect, render_template, request, url_for

from auth import role_required
from db import get_db
from photos import get_token_photo

bp = Blueprint("inventory", __name__, url_prefix="/medicines")


def add_medicine(name, category, low_stock_threshold, units, photo_path=None):
    if not units:
        raise ValueError("medicine must have at least one unit")

    unit_names = [u["unit_name"] for u in units]
    duplicates = {n for n in unit_names if unit_names.count(n) > 1}
    if duplicates:
        raise ValueError(f"duplicate unit name(s) not allowed: {', '.join(sorted(duplicates))}")

    # Validate all units have positive qty_in_base_units and non-negative prices
    for u in units:
        if not isinstance(u["qty_in_base_units"], int) or u["qty_in_base_units"] < 1:
            raise ValueError(f"unit '{u['unit_name']}' must have qty_in_base_units >= 1")
        if u["price"] < 0:
            raise ValueError(f"unit '{u['unit_name']}' price cannot be negative")

    base_units = [u for u in units if u["qty_in_base_units"] == 1]
    if len(base_units) != 1:
        raise ValueError("medicine must have exactly one base unit (qty_in_base_units = 1)")

    db = get_db()
    cur = db.execute(
        "INSERT INTO medicines (name, category, photo_path, stock_in_base_units, low_stock_threshold) "
        "VALUES (?, ?, ?, 0, ?)",
        (name, category, photo_path, low_stock_threshold),
    )
    medicine_id = cur.lastrowid
    for u in units:
        db.execute(
            "INSERT INTO medicine_units (medicine_id, unit_name, qty_in_base_units, price) "
            "VALUES (?, ?, ?, ?)",
            (medicine_id, u["unit_name"], u["qty_in_base_units"], u["price"]),
        )
    db.commit()
    return medicine_id


def set_medicine_photo(medicine_id, photo_path):
    db = get_db()
    db.execute("UPDATE medicines SET photo_path = ? WHERE id = ?", (photo_path, medicine_id))
    db.commit()


def list_medicines():
    db = get_db()
    return db.execute("SELECT * FROM medicines ORDER BY name").fetchall()


def get_medicine(medicine_id):
    db = get_db()
    return db.execute("SELECT * FROM medicines WHERE id = ?", (medicine_id,)).fetchone()


def get_medicine_units(medicine_id):
    db = get_db()
    return db.execute(
        "SELECT * FROM medicine_units WHERE medicine_id = ? ORDER BY qty_in_base_units ASC",
        (medicine_id,),
    ).fetchall()


def search_medicines(query):
    db = get_db()
    return db.execute(
        "SELECT * FROM medicines WHERE name LIKE ? ORDER BY name",
        (f"%{query}%",),
    ).fetchall()


def add_stock(medicine_id, unit_name, quantity):
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError("quantity must be a whole number")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    db = get_db()
    unit_row = db.execute(
        "SELECT qty_in_base_units FROM medicine_units WHERE medicine_id = ? AND unit_name = ?",
        (medicine_id, unit_name),
    ).fetchone()
    if unit_row is None:
        raise ValueError(f"unknown unit '{unit_name}' for medicine {medicine_id}")
    base_units_added = unit_row["qty_in_base_units"] * quantity
    db.execute(
        "UPDATE medicines SET stock_in_base_units = stock_in_base_units + ? WHERE id = ?",
        (base_units_added, medicine_id),
    )
    db.commit()
    return db.execute(
        "SELECT stock_in_base_units FROM medicines WHERE id = ?", (medicine_id,)
    ).fetchone()["stock_in_base_units"]


def low_stock_medicines():
    db = get_db()
    return db.execute(
        "SELECT * FROM medicines WHERE stock_in_base_units < low_stock_threshold ORDER BY name"
    ).fetchall()


def unit_price_breakdown(medicine_id):
    return [
        {
            "unit_name": u["unit_name"],
            "price": u["price"],
            "price_per_base_unit": round(u["price"] / u["qty_in_base_units"], 2),
        }
        for u in get_medicine_units(medicine_id)
    ]


@bp.route("/")
@role_required("admin", "staff")
def list_medicines_view():
    medicines = list_medicines()
    price_breakdowns = {m["id"]: unit_price_breakdown(m["id"]) for m in medicines}
    return render_template(
        "medicines.html", medicines=medicines, price_breakdowns=price_breakdowns
    )


@bp.route("/add", methods=["GET", "POST"])
@role_required("admin")
def add_medicine_view():
    if request.method == "POST":
        try:
            unit_names = request.form.getlist("unit_name")
            unit_qtys = request.form.getlist("unit_qty")
            unit_prices = request.form.getlist("unit_price")
            units = [
                {"unit_name": n, "qty_in_base_units": int(q), "price": round(float(p), 2)}
                for n, q, p in zip(unit_names, unit_qtys, unit_prices)
                if n.strip()
            ]
            photo_token = request.form.get("photo_token")
            photo_path = get_token_photo(photo_token) if photo_token else None
            add_medicine(
                request.form["name"],
                request.form["category"],
                int(request.form["low_stock_threshold"]),
                units,
                photo_path=photo_path,
            )
            return redirect(url_for("inventory.list_medicines_view"))
        except ValueError as e:
            flash(str(e))
        except (KeyError, TypeError) as e:
            flash("Invalid form input")
    return render_template("medicine_add.html")


@bp.route("/<int:medicine_id>/add-stock", methods=["GET", "POST"])
@role_required("admin")
def add_stock_view(medicine_id):
    medicine = get_medicine(medicine_id)
    if request.method == "POST":
        try:
            add_stock(medicine_id, request.form["unit_name"], int(request.form["quantity"]))
            return redirect(url_for("inventory.list_medicines_view"))
        except ValueError as e:
            flash(str(e))
        except (KeyError, TypeError) as e:
            flash("Invalid form input")
    return render_template(
        "add_stock.html", medicine=medicine, units=get_medicine_units(medicine_id)
    )
