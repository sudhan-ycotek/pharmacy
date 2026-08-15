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


def make_stock(medicine_id, unit_name="Tablet", quantity=100,
               cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5):
    add_stock(medicine_id, unit_name, quantity, cost_price_per_base_unit, mrp_per_base_unit)
