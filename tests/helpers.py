from inventory import add_medicine


def make_box_file_medicine(name="Cetamol", low_stock_threshold=50, tablets_per_file=20, files_per_box=12,
                            price_per_box=480.0, price_per_file=45.0, price_per_tablet=2.5):
    return add_medicine(
        name, "box_file", low_stock_threshold,
        tablets_per_file=tablets_per_file, files_per_box=files_per_box,
        price_per_box=price_per_box, price_per_file=price_per_file, price_per_tablet=price_per_tablet,
    )


def make_bottled_medicine(name="Cough Syrup", low_stock_threshold=5, unit_name="Bottle", unit_price=120.0):
    return add_medicine(name, "bottled_other", low_stock_threshold, unit_name=unit_name, unit_price=unit_price)
