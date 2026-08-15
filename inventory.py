from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from auth import current_user, role_required
from db import get_db
from photos import get_token_photo

bp = Blueprint("inventory", __name__, url_prefix="/medicines")

ADJUSTMENT_REASONS = ("damaged", "lost", "found", "correction", "other")


def _positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _non_negative_price(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _valid_percent(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100


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


def _apply_stock_receipt(db, medicine_id, unit_name, quantity, cost_price_per_base_unit,
                          mrp_per_base_unit, purchase_bill_id=None, cost_currency="NPR",
                          cost_price_original=None):
    """Validate and INSERT one new stock_receipts row, bumping medicines.stock_in_base_units
    and overwriting its current cost/MRP (last price wins).

    Does not commit -- callers that insert several receipts in one purchase bill
    control the transaction boundary themselves, the same way create_sale()
    commits once after writing every line item.
    """
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError("quantity must be a whole number")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if not _non_negative_price(cost_price_per_base_unit):
        raise ValueError("cost price must be a non-negative number")
    if not _non_negative_price(mrp_per_base_unit):
        raise ValueError("MRP must be a non-negative number")

    unit_row = db.execute(
        "SELECT qty_in_base_units FROM medicine_units WHERE medicine_id = ? AND unit_name = ?",
        (medicine_id, unit_name),
    ).fetchone()
    if unit_row is None:
        raise ValueError(f"unknown unit '{unit_name}' for medicine {medicine_id}")

    base_units_received = unit_row["qty_in_base_units"] * quantity
    cost_price_per_base_unit = round(cost_price_per_base_unit, 2)
    mrp_per_base_unit = round(mrp_per_base_unit, 2)
    if cost_price_original is None:
        cost_price_original = cost_price_per_base_unit

    cur = db.execute(
        """
        INSERT INTO stock_receipts
            (medicine_id, unit_name, quantity, qty_in_base_units, base_units_received,
             cost_currency, cost_price_original, cost_price_per_base_unit, mrp_per_base_unit,
             purchase_bill_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (medicine_id, unit_name, quantity, unit_row["qty_in_base_units"], base_units_received,
         cost_currency, round(cost_price_original, 2), cost_price_per_base_unit, mrp_per_base_unit,
         purchase_bill_id),
    )
    db.execute(
        "UPDATE medicines SET stock_in_base_units = stock_in_base_units + ?, "
        "cost_price_per_base_unit = ?, mrp_per_base_unit = ? WHERE id = ?",
        (base_units_received, cost_price_per_base_unit, mrp_per_base_unit, medicine_id),
    )
    return cur.lastrowid


def add_stock(medicine_id, unit_name, quantity, cost_price_per_base_unit, mrp_per_base_unit):
    db = get_db()
    _apply_stock_receipt(db, medicine_id, unit_name, quantity, cost_price_per_base_unit, mrp_per_base_unit)
    db.commit()
    return db.execute(
        "SELECT stock_in_base_units FROM medicines WHERE id = ?", (medicine_id,)
    ).fetchone()["stock_in_base_units"]


def record_stock_adjustment(medicine_id, unit_name, quantity, direction, reason, user_id, note=None):
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError("quantity must be a whole number")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if direction not in ("increase", "decrease"):
        raise ValueError("direction must be 'increase' or 'decrease'")
    if reason not in ADJUSTMENT_REASONS:
        raise ValueError(f"reason must be one of: {', '.join(ADJUSTMENT_REASONS)}")

    db = get_db()
    medicine = db.execute("SELECT * FROM medicines WHERE id = ?", (medicine_id,)).fetchone()
    if medicine is None:
        raise ValueError(f"medicine {medicine_id} not found")
    unit_row = db.execute(
        "SELECT qty_in_base_units FROM medicine_units WHERE medicine_id = ? AND unit_name = ?",
        (medicine_id, unit_name),
    ).fetchone()
    if unit_row is None:
        raise ValueError(f"unknown unit '{unit_name}' for medicine {medicine_id}")

    base_units = unit_row["qty_in_base_units"] * quantity
    if direction == "decrease":
        if medicine["stock_in_base_units"] < base_units:
            raise ValueError("cannot remove more stock than is currently available")
        base_units_delta = -base_units
    else:
        base_units_delta = base_units

    db.execute(
        "INSERT INTO stock_adjustments (medicine_id, unit_name, quantity, qty_in_base_units, "
        "base_units_delta, reason, note, recorded_by_user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (medicine_id, unit_name, quantity, unit_row["qty_in_base_units"], base_units_delta,
         reason, note, user_id),
    )
    db.execute(
        "UPDATE medicines SET stock_in_base_units = stock_in_base_units + ? WHERE id = ?",
        (base_units_delta, medicine_id),
    )
    db.commit()
    return db.execute(
        "SELECT stock_in_base_units FROM medicines WHERE id = ?", (medicine_id,)
    ).fetchone()["stock_in_base_units"]


def list_stock_receipts(medicine_id):
    db = get_db()
    return db.execute(
        "SELECT sr.*, v.name AS vendor_name FROM stock_receipts sr "
        "LEFT JOIN purchase_bills pb ON pb.id = sr.purchase_bill_id "
        "LEFT JOIN vendors v ON v.id = pb.vendor_id "
        "WHERE sr.medicine_id = ? ORDER BY sr.created_at DESC",
        (medicine_id,),
    ).fetchall()


def list_stock_adjustments(medicine_id):
    db = get_db()
    return db.execute(
        "SELECT * FROM stock_adjustments WHERE medicine_id = ? ORDER BY created_at DESC",
        (medicine_id,),
    ).fetchall()


def update_max_discount(medicine_id, max_discount_percent):
    if not _valid_percent(max_discount_percent):
        raise ValueError("max discount percent must be between 0 and 100")
    db = get_db()
    db.execute(
        "UPDATE medicines SET max_discount_percent = ? WHERE id = ?",
        (round(max_discount_percent, 2), medicine_id),
    )
    db.commit()


def recent_stock_receipts(days=7):
    db = get_db()
    return db.execute(
        "SELECT sr.*, m.name AS medicine_name FROM stock_receipts sr "
        "JOIN medicines m ON m.id = sr.medicine_id "
        f"WHERE sr.created_at >= datetime('now', 'localtime', '-{days} days') "
        "ORDER BY sr.created_at DESC",
    ).fetchall()


def low_stock_medicines():
    db = get_db()
    return db.execute(
        """
        SELECT m.*,
               (SELECT MAX(sr.created_at) FROM stock_receipts sr
                WHERE sr.medicine_id = m.id) AS last_restock
        FROM medicines m
        WHERE m.stock_in_base_units < m.low_stock_threshold
        ORDER BY m.name
        """
    ).fetchall()


def daily_stock_received(days=7):
    db = get_db()
    return db.execute(
        "SELECT date(created_at) AS day, COALESCE(SUM(base_units_received), 0) AS received "
        "FROM stock_receipts "
        f"WHERE date(created_at) >= date('now', 'localtime', '-{days} days') "
        "GROUP BY day"
    ).fetchall()


def total_stock_units():
    db = get_db()
    return db.execute(
        "SELECT COALESCE(SUM(stock_in_base_units), 0) AS total FROM medicines"
    ).fetchone()["total"]


def stock_received_this_month():
    db = get_db()
    return db.execute(
        "SELECT COALESCE(SUM(base_units_received), 0) AS total FROM stock_receipts "
        "WHERE date(created_at) >= date('now', 'localtime', 'start of month')"
    ).fetchone()["total"]


def unit_prices(medicine_id):
    medicine = get_medicine(medicine_id)
    result = []
    for u in get_medicine_units(medicine_id):
        priced = medicine["mrp_per_base_unit"] > 0
        price = round(medicine["mrp_per_base_unit"] * u["qty_in_base_units"], 2) if priced else None
        result.append({"unit_name": u["unit_name"], "price": price})
    return result


@bp.route("/")
@role_required("admin", "staff")
def list_medicines_view():
    medicines = list_medicines()
    prices = {m["id"]: unit_prices(m["id"]) for m in medicines}
    return render_template("medicines.html", medicines=medicines, prices=prices)


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
            elif action == "adjust":
                record_stock_adjustment(
                    medicine_id, request.form["unit_name"], int(request.form["quantity"]),
                    request.form["direction"], request.form["reason"],
                    current_user()["id"], note=request.form.get("note") or None,
                )
            else:
                raise ValueError("unknown action — stock is now received via a vendor purchase bill")
            return redirect(url_for("inventory.add_stock_view", medicine_id=medicine_id))
        except ValueError as e:
            flash(str(e))
        except (KeyError, TypeError):
            flash("Invalid form input")
    return render_template(
        "add_stock.html", medicine=medicine, units=get_medicine_units(medicine_id),
        stock_receipts=list_stock_receipts(medicine_id),
        stock_adjustments=list_stock_adjustments(medicine_id),
    )


@bp.route("/<int:medicine_id>/max-discount", methods=["POST"])
@role_required("admin")
def update_max_discount_ajax(medicine_id):
    try:
        update_max_discount(medicine_id, float(request.json["max_discount_percent"]))
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"max_discount_percent": get_medicine(medicine_id)["max_discount_percent"]})
