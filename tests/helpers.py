from inventory import add_medicine, add_stock


def make_box_file_medicine(name="Cetamol", low_stock_threshold=50, tablets_per_file=20, files_per_box=12,
                            max_discount_percent=0):
    return add_medicine(
        name, "box_file", low_stock_threshold, max_discount_percent=max_discount_percent,
        tablets_per_file=tablets_per_file, files_per_box=files_per_box,
    )


def make_bottled_medicine(name="Cough Syrup", low_stock_threshold=5, unit_name="Bottle", max_discount_percent=0):
    return add_medicine(name, "bottled_other", low_stock_threshold,
                         max_discount_percent=max_discount_percent, unit_name=unit_name)


def make_batch(medicine_id, unit_name="Tablet", quantity=100, expiry_date="2030-01-01",
               cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5):
    add_stock(medicine_id, unit_name, quantity, expiry_date, cost_price_per_base_unit, mrp_per_base_unit)
    from inventory import get_db
    db = get_db()
    return db.execute(
        "SELECT id FROM medicine_batches WHERE medicine_id = ? AND expiry_date = ? "
        "AND cost_price_per_base_unit = ?",
        (medicine_id, expiry_date, cost_price_per_base_unit),
    ).fetchone()["id"]
