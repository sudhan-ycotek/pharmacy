import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from auth import current_user, role_required
from companies import get_company, list_companies
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


def _compute_units(packaging_type, tablets_per_file=None, files_per_box=None, unit_name=None):
    """Turn a packaging configuration into the medicine_units rows it implies.

    Shared by add_medicine and edit_medicine so the box_file/bottled_other
    branching -- and what counts as "the same" packaging configuration for
    edit_medicine's locking check -- lives in exactly one place.
    """
    if packaging_type == "box_file":
        if not (_positive_int(tablets_per_file) and _positive_int(files_per_box)):
            raise ValueError("tablets per file and files per box must be positive whole numbers")
        return [
            {"unit_name": "Box", "qty_in_base_units": files_per_box * tablets_per_file, "is_sellable": 0},
            {"unit_name": "File", "qty_in_base_units": tablets_per_file, "is_sellable": 1},
            {"unit_name": "Tablet", "qty_in_base_units": 1, "is_sellable": 1},
        ]
    elif packaging_type == "bottled_other":
        if not unit_name or not unit_name.strip():
            raise ValueError("unit name is required")
        return [{"unit_name": unit_name.strip(), "qty_in_base_units": 1, "is_sellable": 1}]
    else:
        raise ValueError("packaging_type must be 'box_file' or 'bottled_other'")


def _units_signature(units):
    return sorted((u["unit_name"], u["qty_in_base_units"], u["is_sellable"]) for u in units)


def _next_medicine_code(db):
    """MED-#### code: MAX(existing numeric suffix) + 1.

    Same widen-past-9999-rather-than-block scheme as vendor codes.
    """
    existing_numbers = []
    for row in db.execute("SELECT code FROM medicines WHERE code IS NOT NULL"):
        code = row["code"]
        if code and code.startswith("MED-") and code[4:].isdigit():
            existing_numbers.append(int(code[4:]))
    next_number = max(existing_numbers, default=0) + 1
    return f"MED-{next_number:04d}"


def add_medicine(name, packaging_type, low_stock_threshold, max_discount_percent=0,
                  photo_path=None, tablets_per_file=None, files_per_box=None, unit_name=None,
                  company_id=None, packing=None):
    if not _valid_percent(max_discount_percent):
        raise ValueError("max discount percent must be between 0 and 100")
    if company_id is not None and get_company(company_id) is None:
        raise ValueError(f"company {company_id} not found")

    units = _compute_units(packaging_type, tablets_per_file, files_per_box, unit_name)

    db = get_db()
    code = _next_medicine_code(db)
    cur = db.execute(
        "INSERT INTO medicines (code, name, packaging_type, photo_path, stock_in_base_units, "
        "low_stock_threshold, max_discount_percent, company_id, packing) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)",
        (code, name, packaging_type, photo_path, low_stock_threshold, round(max_discount_percent, 2),
         company_id, (packing or "").strip() or None),
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


def medicine_has_stock_history(medicine_id):
    """True if this medicine has ever had a stock receipt, sale, or stock
    adjustment recorded against it -- checked regardless of *current* stock
    level, since a medicine sold down to zero still has historical unit-ratio
    snapshots (past stock_receipts/sale_items rows) that depend on the base
    unit conversions staying exactly as they were.
    """
    db = get_db()
    for table in ("stock_receipts", "sale_items", "stock_adjustments"):
        row = db.execute(f"SELECT 1 FROM {table} WHERE medicine_id = ? LIMIT 1", (medicine_id,)).fetchone()
        if row is not None:
            return True
    return False


def edit_medicine(medicine_id, name, packaging_type, low_stock_threshold, max_discount_percent=0,
                   photo_path=None, tablets_per_file=None, files_per_box=None, unit_name=None,
                   company_id=None, packing=None):
    """Update an existing medicine.

    name/company/packing/threshold/discount/photo can always change. Changing
    packaging_type or the base-unit ratios (tablets_per_file/files_per_box for
    box_file, unit_name for bottled_other) is only allowed while the medicine
    has no stock history -- once medicine_has_stock_history() is true, this is
    rejected server-side (not merely hidden in the UI), because every past
    stock_receipts/sale_items/stock_adjustments row depends on those ratios
    staying exactly as they were.
    """
    db = get_db()
    medicine = db.execute("SELECT * FROM medicines WHERE id = ?", (medicine_id,)).fetchone()
    if medicine is None:
        raise ValueError(f"medicine {medicine_id} not found")
    if not _valid_percent(max_discount_percent):
        raise ValueError("max discount percent must be between 0 and 100")
    if company_id is not None and get_company(company_id) is None:
        raise ValueError(f"company {company_id} not found")

    proposed_units = _compute_units(packaging_type, tablets_per_file, files_per_box, unit_name)

    if medicine_has_stock_history(medicine_id):
        current_units = [dict(u) for u in get_medicine_units(medicine_id)]
        if (packaging_type != medicine["packaging_type"]
                or _units_signature(proposed_units) != _units_signature(current_units)):
            raise ValueError(
                "packaging type and base-unit ratios can't change once stock history "
                "exists for this medicine"
            )
    else:
        db.execute("DELETE FROM medicine_units WHERE medicine_id = ?", (medicine_id,))
        for u in proposed_units:
            db.execute(
                "INSERT INTO medicine_units (medicine_id, unit_name, qty_in_base_units, is_sellable) "
                "VALUES (?, ?, ?, ?)",
                (medicine_id, u["unit_name"], u["qty_in_base_units"], u["is_sellable"]),
            )

    db.execute(
        "UPDATE medicines SET name = ?, packaging_type = ?, low_stock_threshold = ?, "
        "max_discount_percent = ?, photo_path = ?, company_id = ?, packing = ? WHERE id = ?",
        (name, packaging_type, low_stock_threshold, round(max_discount_percent, 2),
         photo_path, company_id, (packing or "").strip() or None, medicine_id),
    )
    db.commit()


def set_medicine_photo(medicine_id, photo_path):
    db = get_db()
    db.execute("UPDATE medicines SET photo_path = ? WHERE id = ?", (photo_path, medicine_id))
    db.commit()


def list_medicines():
    db = get_db()
    return db.execute(
        "SELECT m.*, c.name AS company_name FROM medicines m "
        "LEFT JOIN companies c ON c.id = m.company_id ORDER BY m.name"
    ).fetchall()


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
        "SELECT m.*, c.name AS company_name FROM medicines m "
        "LEFT JOIN companies c ON c.id = m.company_id "
        "WHERE m.name LIKE ? ORDER BY m.name",
        (f"%{query}%",),
    ).fetchall()


def _apply_stock_receipt(db, medicine_id, unit_name, quantity, cost_price_per_base_unit,
                          mrp_per_base_unit, purchase_bill_id=None, cost_currency="NPR",
                          cost_price_original=None, mrp_currency="NPR", mrp_original=None,
                          batch_number=None, expiry_date=None):
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
    if expiry_date is not None:
        try:
            datetime.date.fromisoformat(expiry_date)
        except (ValueError, TypeError):
            raise ValueError("expiry date must be in YYYY-MM-DD format")

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
    if mrp_original is None:
        mrp_original = mrp_per_base_unit
    batch_number = (batch_number or "").strip() or None

    cur = db.execute(
        """
        INSERT INTO stock_receipts
            (medicine_id, unit_name, quantity, qty_in_base_units, base_units_received,
             cost_currency, cost_price_original, cost_price_per_base_unit, mrp_per_base_unit,
             purchase_bill_id, batch_number, expiry_date, mrp_currency, mrp_original)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (medicine_id, unit_name, quantity, unit_row["qty_in_base_units"], base_units_received,
         cost_currency, round(cost_price_original, 2), cost_price_per_base_unit, mrp_per_base_unit,
         purchase_bill_id, batch_number, expiry_date, mrp_currency, round(mrp_original, 2)),
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


def stock_balance_as_of(as_of_date, price_basis="cost"):
    """Reconstruct every medicine's stock quantity as of a given date and value it
    at the medicine's *current* cost or MRP.

    The quantity is a signed-delta reconstruction across every stock-moving table
    (stock_receipts +, stock_adjustments +/-, sale_items -, purchase_return_items -,
    sale_return_items +) via one UNION ALL + GROUP BY -- not read from
    medicines.stock_in_base_units, which only ever reflects "now". Each branch is
    filtered to its own date column being on/before as_of_date, so an earlier
    as_of_date naturally excludes later activity; voided sales/purchase returns/
    sale returns are excluded via WHERE ... = 0 on the tables that actually carry
    a voided flag (stock_receipts and stock_adjustments have none). Medicines with
    no matching activity still appear (at balance 0) via the LEFT JOIN onto
    medicines.

    Valuation always uses the medicine's *current* cost_price_per_base_unit or
    mrp_per_base_unit -- a historical per-date cost isn't reconstructable without
    true batch (FIFO) consumption tracking, which this system intentionally does
    not implement. This is a deliberate scope limit, not a bug.
    """
    if price_basis not in ("cost", "mrp"):
        raise ValueError("price_basis must be 'cost' or 'mrp'")
    price_column = "cost_price_per_base_unit" if price_basis == "cost" else "mrp_per_base_unit"

    db = get_db()
    return db.execute(
        f"""
        SELECT m.id AS medicine_id, m.name, m.packaging_type,
               m.{price_column} AS unit_price,
               COALESCE(SUM(delta.units), 0) AS balance,
               COALESCE(SUM(delta.units), 0) * m.{price_column} AS value
        FROM medicines m
        LEFT JOIN (
            SELECT medicine_id, base_units_received AS units
            FROM stock_receipts
            WHERE date(created_at) <= ?

            UNION ALL
            SELECT medicine_id, base_units_delta AS units
            FROM stock_adjustments
            WHERE date(created_at) <= ?

            UNION ALL
            SELECT si.medicine_id, -(si.qty_in_base_units * si.quantity) AS units
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            WHERE s.voided = 0 AND date(s.timestamp) <= ?

            UNION ALL
            SELECT pri.medicine_id, -pri.base_units_returned AS units
            FROM purchase_return_items pri
            JOIN purchase_returns pr ON pr.id = pri.purchase_return_id
            WHERE pr.voided = 0 AND date(pr.return_date) <= ?

            UNION ALL
            SELECT sri.medicine_id, sri.base_units_returned AS units
            FROM sale_return_items sri
            JOIN sale_returns sr ON sr.id = sri.sale_return_id
            WHERE sr.voided = 0 AND date(sr.return_date) <= ?
        ) delta ON delta.medicine_id = m.id
        GROUP BY m.id
        ORDER BY m.name
        """,
        (as_of_date, as_of_date, as_of_date, as_of_date, as_of_date),
    ).fetchall()


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
    return render_template(
        "medicines.html", medicines=medicines, prices=prices, companies=list_companies()
    )


def _parse_medicine_form(form):
    """Parse the fields shared by medicine_form.html's add and edit posts.

    Raises ValueError for bad category/number input (caught by the callers'
    flash-and-redisplay handling, same as before this was factored out).
    """
    packaging_type = form["packaging_type"]
    if packaging_type not in ("box_file", "bottled_other"):
        raise ValueError("invalid category selected")

    try:
        if packaging_type == "box_file":
            unit_kwargs = {
                "tablets_per_file": int(form["tablets_per_file"]),
                "files_per_box": int(form["files_per_box"]),
            }
        else:
            unit_name = form.get("unit_type", "")
            if unit_name == "Other":
                unit_name = form.get("custom_unit_name", "").strip()
            unit_kwargs = {"unit_name": unit_name}
        low_stock_threshold = int(form["low_stock_threshold"])
        max_discount_percent = float(form["max_discount_percent"])
    except ValueError:
        raise ValueError("Enter a valid number for every quantity and discount field")

    company_id_raw = form.get("company_id")
    try:
        company_id = int(company_id_raw) if company_id_raw else None
    except ValueError:
        raise ValueError("invalid company selected")
    packing = form.get("packing") or None

    return packaging_type, unit_kwargs, low_stock_threshold, max_discount_percent, company_id, packing


@bp.route("/add", methods=["GET", "POST"])
@role_required("admin")
def add_medicine_view():
    if request.method == "POST":
        try:
            packaging_type, unit_kwargs, low_stock_threshold, max_discount_percent, company_id, packing = \
                _parse_medicine_form(request.form)
            photo_token = request.form.get("photo_token")
            photo_path = get_token_photo(photo_token) if photo_token else None

            add_medicine(
                request.form["name"],
                packaging_type,
                low_stock_threshold,
                max_discount_percent=max_discount_percent,
                photo_path=photo_path,
                company_id=company_id,
                packing=packing,
                **unit_kwargs,
            )
            return redirect(url_for("inventory.list_medicines_view"))
        except ValueError as e:
            flash(str(e))
        except (KeyError, TypeError):
            flash("Invalid form input")
    return render_template("medicine_form.html", medicine=None, units=[], has_stock_history=False, company=None)


@bp.route("/<int:medicine_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_medicine_view(medicine_id):
    medicine = get_medicine(medicine_id)
    if medicine is None:
        return "Medicine not found", 404
    has_history = medicine_has_stock_history(medicine_id)

    if request.method == "POST":
        try:
            packaging_type, unit_kwargs, low_stock_threshold, max_discount_percent, company_id, packing = \
                _parse_medicine_form(request.form)
            photo_token = request.form.get("photo_token")
            photo_path = get_token_photo(photo_token) if photo_token else medicine["photo_path"]

            edit_medicine(
                medicine_id,
                request.form["name"],
                packaging_type,
                low_stock_threshold,
                max_discount_percent=max_discount_percent,
                photo_path=photo_path,
                company_id=company_id,
                packing=packing,
                **unit_kwargs,
            )
            return redirect(url_for("inventory.list_medicines_view"))
        except ValueError as e:
            flash(str(e))
        except (KeyError, TypeError):
            flash("Invalid form input")
    return render_template(
        "medicine_form.html", medicine=medicine, units=get_medicine_units(medicine_id),
        has_stock_history=has_history,
        company=get_company(medicine["company_id"]) if medicine["company_id"] else None,
    )


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


@bp.route("/stock-balance")
@role_required("admin")
def stock_balance_view():
    as_of_date = request.args.get("as_of_date") or datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(as_of_date)
    except ValueError:
        flash("Invalid date -- showing today's balance instead")
        as_of_date = datetime.date.today().isoformat()

    price_basis = request.args.get("price_basis") or "cost"
    if price_basis not in ("cost", "mrp"):
        price_basis = "cost"

    rows = stock_balance_as_of(as_of_date, price_basis=price_basis)
    total_value = round(sum(r["value"] for r in rows), 2)
    return render_template(
        "stock_balance.html", rows=rows, as_of_date=as_of_date, price_basis=price_basis,
        total_value=total_value,
    )
