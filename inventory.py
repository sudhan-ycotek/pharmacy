from flask import Blueprint, flash, redirect, render_template, request, url_for

from auth import role_required
from db import get_db
from photos import get_token_photo

bp = Blueprint("inventory", __name__, url_prefix="/medicines")


def add_medicine(name, packaging_type, low_stock_threshold, photo_path=None,
                  tablets_per_file=None, files_per_box=None,
                  price_per_box=None, price_per_file=None, price_per_tablet=None,
                  unit_name=None, unit_price=None):
    def _positive_int(value):
        return isinstance(value, int) and not isinstance(value, bool) and value >= 1

    def _non_negative_price(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0

    if packaging_type == "box_file":
        if not (_positive_int(tablets_per_file) and _positive_int(files_per_box)):
            raise ValueError("tablets per file and files per box must be positive whole numbers")
        if not all(_non_negative_price(p) for p in (price_per_box, price_per_file, price_per_tablet)):
            raise ValueError("box, file, and tablet prices must all be set and non-negative")
        units = [
            {"unit_name": "Box", "qty_in_base_units": files_per_box * tablets_per_file,
             "price": round(price_per_box, 2), "is_sellable": 0},
            {"unit_name": "File", "qty_in_base_units": tablets_per_file,
             "price": round(price_per_file, 2), "is_sellable": 1},
            {"unit_name": "Tablet", "qty_in_base_units": 1,
             "price": round(price_per_tablet, 2), "is_sellable": 1},
        ]
    elif packaging_type == "bottled_other":
        if not unit_name or not unit_name.strip():
            raise ValueError("unit name is required")
        if not _non_negative_price(unit_price):
            raise ValueError("unit price must be a non-negative number")
        units = [
            {"unit_name": unit_name.strip(), "qty_in_base_units": 1,
             "price": round(unit_price, 2), "is_sellable": 1},
        ]
    else:
        raise ValueError("packaging_type must be 'box_file' or 'bottled_other'")

    db = get_db()
    cur = db.execute(
        "INSERT INTO medicines (name, packaging_type, photo_path, stock_in_base_units, low_stock_threshold) "
        "VALUES (?, ?, ?, 0, ?)",
        (name, packaging_type, photo_path, low_stock_threshold),
    )
    medicine_id = cur.lastrowid
    for u in units:
        db.execute(
            "INSERT INTO medicine_units (medicine_id, unit_name, qty_in_base_units, price, is_sellable) "
            "VALUES (?, ?, ?, ?, ?)",
            (medicine_id, u["unit_name"], u["qty_in_base_units"], u["price"], u["is_sellable"]),
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
                        "price_per_box": round(float(request.form["price_per_box"]), 2),
                        "price_per_file": round(float(request.form["price_per_file"]), 2),
                        "price_per_tablet": round(float(request.form["price_per_tablet"]), 2),
                    }
                else:
                    unit_name = request.form.get("unit_type", "")
                    if unit_name == "Other":
                        unit_name = request.form.get("custom_unit_name", "").strip()
                    kwargs = {
                        "unit_name": unit_name,
                        "unit_price": round(float(request.form["unit_price"]), 2),
                    }
                low_stock_threshold = int(request.form["low_stock_threshold"])
            except ValueError:
                raise ValueError("Enter a valid number for every price and quantity field")

            add_medicine(
                request.form["name"],
                packaging_type,
                low_stock_threshold,
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
