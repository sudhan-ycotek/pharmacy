import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from auth import role_required
from db import get_db
from photos import get_token_photo

bp = Blueprint("inventory", __name__, url_prefix="/medicines")


def _positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _non_negative_price(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _valid_percent(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100


def _parse_future_expiry(value):
    try:
        parsed = datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError("expiry date must be in YYYY-MM-DD format")
    if parsed <= datetime.date.today():
        raise ValueError("expiry date must be in the future")
    return parsed.isoformat()


def add_medicine(name, packaging_type, low_stock_threshold, max_discount_percent=0,
                  photo_path=None, tablets_per_file=None, files_per_box=None, unit_name=None):
    if not _valid_percent(max_discount_percent):
        raise ValueError("max discount percent must be between 0 and 100")

    if packaging_type == "box_file":
        if not (_positive_int(tablets_per_file) and _positive_int(files_per_box)):
            raise ValueError("tablets per file and files per box must be positive whole numbers")
        units = [
            {"unit_name": "Box", "qty_in_base_units": files_per_box * tablets_per_file, "is_sellable": 0},
            {"unit_name": "File", "qty_in_base_units": tablets_per_file, "is_sellable": 1},
            {"unit_name": "Tablet", "qty_in_base_units": 1, "is_sellable": 1},
        ]
    elif packaging_type == "bottled_other":
        if not unit_name or not unit_name.strip():
            raise ValueError("unit name is required")
        units = [{"unit_name": unit_name.strip(), "qty_in_base_units": 1, "is_sellable": 1}]
    else:
        raise ValueError("packaging_type must be 'box_file' or 'bottled_other'")

    db = get_db()
    cur = db.execute(
        "INSERT INTO medicines (name, packaging_type, photo_path, stock_in_base_units, "
        "low_stock_threshold, max_discount_percent) VALUES (?, ?, ?, 0, ?, ?)",
        (name, packaging_type, photo_path, low_stock_threshold, round(max_discount_percent, 2)),
    )
    medicine_id = cur.lastrowid
    for u in units:
        db.execute(
            "INSERT INTO medicine_units (medicine_id, unit_name, qty_in_base_units, is_sellable) "
            "VALUES (?, ?, ?, ?)",
            (medicine_id, u["unit_name"], u["qty_in_base_units"], u["is_sellable"]),
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


def sellable_units(medicine_id):
    db = get_db()
    return db.execute(
        "SELECT * FROM medicine_units WHERE medicine_id = ? AND is_sellable = 1 ORDER BY qty_in_base_units ASC",
        (medicine_id,),
    ).fetchall()


def count_medicines():
    db = get_db()
    return db.execute("SELECT COUNT(*) AS c FROM medicines").fetchone()["c"]


def search_medicines(query):
    db = get_db()
    return db.execute(
        "SELECT * FROM medicines WHERE name LIKE ? ORDER BY name",
        (f"%{query}%",),
    ).fetchall()


def add_stock(medicine_id, unit_name, quantity, expiry_date, cost_price_per_base_unit, mrp_per_base_unit):
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError("quantity must be a whole number")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if not _non_negative_price(cost_price_per_base_unit):
        raise ValueError("cost price must be a non-negative number")
    if not _non_negative_price(mrp_per_base_unit):
        raise ValueError("MRP must be a non-negative number")
    expiry = _parse_future_expiry(expiry_date)

    db = get_db()
    unit_row = db.execute(
        "SELECT qty_in_base_units FROM medicine_units WHERE medicine_id = ? AND unit_name = ?",
        (medicine_id, unit_name),
    ).fetchone()
    if unit_row is None:
        raise ValueError(f"unknown unit '{unit_name}' for medicine {medicine_id}")

    base_units_added = unit_row["qty_in_base_units"] * quantity
    cost_price_per_base_unit = round(cost_price_per_base_unit, 2)
    mrp_per_base_unit = round(mrp_per_base_unit, 2)

    db.execute(
        """
        INSERT INTO medicine_batches
            (medicine_id, expiry_date, cost_price_per_base_unit, mrp_per_base_unit,
             quantity_received, quantity_remaining)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(medicine_id, expiry_date, cost_price_per_base_unit) DO UPDATE SET
            quantity_received = quantity_received + excluded.quantity_received,
            quantity_remaining = quantity_remaining + excluded.quantity_remaining,
            mrp_per_base_unit = excluded.mrp_per_base_unit
        """,
        (medicine_id, expiry, cost_price_per_base_unit, mrp_per_base_unit,
         base_units_added, base_units_added),
    )
    db.execute(
        "UPDATE medicines SET stock_in_base_units = stock_in_base_units + ? WHERE id = ?",
        (base_units_added, medicine_id),
    )
    db.commit()
    return db.execute(
        "SELECT stock_in_base_units FROM medicines WHERE id = ?", (medicine_id,)
    ).fetchone()["stock_in_base_units"]


def remove_stock(batch_id, unit_name, quantity):
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError("quantity must be a whole number")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    db = get_db()
    batch = db.execute("SELECT * FROM medicine_batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError(f"batch {batch_id} not found")
    unit_row = db.execute(
        "SELECT qty_in_base_units FROM medicine_units WHERE medicine_id = ? AND unit_name = ?",
        (batch["medicine_id"], unit_name),
    ).fetchone()
    if unit_row is None:
        raise ValueError(f"unknown unit '{unit_name}' for medicine {batch['medicine_id']}")
    base_units_removed = unit_row["qty_in_base_units"] * quantity
    if batch["quantity_remaining"] < base_units_removed:
        raise ValueError("cannot remove more stock than is currently in this batch")
    db.execute(
        "UPDATE medicine_batches SET quantity_remaining = quantity_remaining - ? WHERE id = ?",
        (base_units_removed, batch_id),
    )
    db.execute(
        "UPDATE medicines SET stock_in_base_units = stock_in_base_units - ? WHERE id = ?",
        (base_units_removed, batch["medicine_id"]),
    )
    db.commit()
    return db.execute(
        "SELECT stock_in_base_units FROM medicines WHERE id = ?", (batch["medicine_id"],)
    ).fetchone()["stock_in_base_units"]


def list_batches(medicine_id, only_available=True):
    db = get_db()
    query = "SELECT * FROM medicine_batches WHERE medicine_id = ?"
    if only_available:
        query += " AND quantity_remaining > 0"
    query += " ORDER BY expiry_date ASC"
    return db.execute(query, (medicine_id,)).fetchall()


def get_batch(batch_id):
    db = get_db()
    return db.execute("SELECT * FROM medicine_batches WHERE id = ?", (batch_id,)).fetchone()


def update_max_discount(medicine_id, max_discount_percent):
    if not _valid_percent(max_discount_percent):
        raise ValueError("max discount percent must be between 0 and 100")
    db = get_db()
    db.execute(
        "UPDATE medicines SET max_discount_percent = ? WHERE id = ?",
        (round(max_discount_percent, 2), medicine_id),
    )
    db.commit()


def recent_batches(days=7):
    db = get_db()
    return db.execute(
        "SELECT mb.*, m.name AS medicine_name FROM medicine_batches mb "
        "JOIN medicines m ON m.id = mb.medicine_id "
        f"WHERE mb.created_at >= datetime('now', 'localtime', '-{days} days') "
        "ORDER BY mb.created_at DESC",
    ).fetchall()


def low_stock_medicines():
    db = get_db()
    return db.execute(
        "SELECT * FROM medicines WHERE stock_in_base_units < low_stock_threshold ORDER BY name"
    ).fetchall()


def unit_price_range(medicine_id):
    db = get_db()
    batch_prices = db.execute(
        "SELECT mrp_per_base_unit FROM medicine_batches WHERE medicine_id = ? AND quantity_remaining > 0",
        (medicine_id,),
    ).fetchall()
    result = []
    for u in get_medicine_units(medicine_id):
        if not batch_prices:
            result.append({"unit_name": u["unit_name"], "min_price": None, "max_price": None})
            continue
        prices = [round(b["mrp_per_base_unit"] * u["qty_in_base_units"], 2) for b in batch_prices]
        result.append({"unit_name": u["unit_name"], "min_price": min(prices), "max_price": max(prices)})
    return result


@bp.route("/")
@role_required("admin", "staff")
def list_medicines_view():
    medicines = list_medicines()
    price_ranges = {m["id"]: unit_price_range(m["id"]) for m in medicines}
    return render_template(
        "medicines.html", medicines=medicines, price_ranges=price_ranges
    )


@bp.route("/add", methods=["GET", "POST"])
@role_required("admin")
def add_medicine_view():
    if request.method == "POST":
        try:
            packaging_type = request.form["packaging_type"]
            photo_token = request.form.get("photo_token")
            photo_path = get_token_photo(photo_token) if photo_token else None
            if packaging_type not in ("box_file", "bottled_other"):
                raise ValueError("invalid category selected")

            try:
                if packaging_type == "box_file":
                    kwargs = {
                        "tablets_per_file": int(request.form["tablets_per_file"]),
                        "files_per_box": int(request.form["files_per_box"]),
                    }
                else:
                    unit_name = request.form.get("unit_type", "")
                    if unit_name == "Other":
                        unit_name = request.form.get("custom_unit_name", "").strip()
                    kwargs = {"unit_name": unit_name}
                low_stock_threshold = int(request.form["low_stock_threshold"])
                max_discount_percent = float(request.form["max_discount_percent"])
            except ValueError:
                raise ValueError("Enter a valid number for every quantity and discount field")

            add_medicine(
                request.form["name"],
                packaging_type,
                low_stock_threshold,
                max_discount_percent=max_discount_percent,
                photo_path=photo_path,
                **kwargs,
            )
            return redirect(url_for("inventory.list_medicines_view"))
        except ValueError as e:
            flash(str(e))
        except (KeyError, TypeError):
            flash("Invalid form input")
    return render_template("medicine_add.html")


@bp.route("/<int:medicine_id>/add-stock", methods=["GET", "POST"])
@role_required("admin")
def add_stock_view(medicine_id):
    medicine = get_medicine(medicine_id)
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "update_discount":
                update_max_discount(medicine_id, float(request.form["max_discount_percent"]))
            elif action == "remove":
                remove_stock(
                    int(request.form["batch_id"]), request.form["unit_name"],
                    int(request.form["quantity"]),
                )
            else:
                add_stock(
                    medicine_id, request.form["unit_name"], int(request.form["quantity"]),
                    request.form["expiry_date"],
                    float(request.form["cost_price_per_base_unit"]),
                    float(request.form["mrp_per_base_unit"]),
                )
            return redirect(url_for("inventory.add_stock_view", medicine_id=medicine_id))
        except ValueError as e:
            flash(str(e))
        except (KeyError, TypeError):
            flash("Invalid form input")
    return render_template(
        "add_stock.html", medicine=medicine, units=get_medicine_units(medicine_id),
        batches=list_batches(medicine_id, only_available=False),
    )
