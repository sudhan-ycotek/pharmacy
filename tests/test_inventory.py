import pytest

from inventory import (
    add_medicine,
    add_stock,
    count_medicines,
    get_medicine_units,
    list_medicines,
    low_stock_medicines,
    search_medicines,
    sellable_units,
    unit_price_breakdown,
)
from helpers import make_bottled_medicine, make_box_file_medicine


def test_add_medicine_box_file_creates_three_units(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        units = get_medicine_units(medicine_id)
        assert [u["unit_name"] for u in units] == ["Tablet", "File", "Box"]
        by_name = {u["unit_name"]: u for u in units}
        assert by_name["Box"]["qty_in_base_units"] == 240
        assert by_name["File"]["qty_in_base_units"] == 20
        assert by_name["Tablet"]["qty_in_base_units"] == 1


def test_add_medicine_box_file_box_is_not_sellable(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        sellable = {u["unit_name"] for u in sellable_units(medicine_id)}
        assert sellable == {"File", "Tablet"}


def test_add_medicine_bottled_other_creates_one_sellable_unit(app):
    with app.app_context():
        medicine_id = make_bottled_medicine()
        units = get_medicine_units(medicine_id)
        assert len(units) == 1
        assert units[0]["unit_name"] == "Bottle"
        sellable = sellable_units(medicine_id)
        assert len(sellable) == 1
        assert sellable[0]["unit_name"] == "Bottle"


def test_add_medicine_rejects_invalid_packaging_type(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "not_a_type", 10)


def test_add_medicine_box_file_rejects_non_positive_conversion_numbers(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "box_file", 10, tablets_per_file=0, files_per_box=12,
                          price_per_box=1.0, price_per_file=1.0, price_per_tablet=1.0)


def test_add_medicine_bottled_other_requires_unit_name(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "bottled_other", 10, unit_name="", unit_price=10.0)


def test_add_medicine_bottled_other_rejects_negative_price(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "bottled_other", 10, unit_name="Bottle", unit_price=-5.0)


def test_add_stock_converts_to_base_units(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        new_total = add_stock(medicine_id, "Box", 2)
        assert new_total == 480


def test_add_stock_unknown_unit_raises(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Pallet", 1)


def test_add_stock_rejects_fractional_quantity(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Box", 2.5)


def test_low_stock_medicines_flags_below_threshold(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(low_stock_threshold=50)
        add_stock(medicine_id, "Tablet", 10)
        low = low_stock_medicines()
        assert any(m["id"] == medicine_id for m in low)


def test_unit_price_breakdown_computes_price_per_base_unit(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        breakdown = unit_price_breakdown(medicine_id)
        by_unit = {b["unit_name"]: b for b in breakdown}
        assert by_unit["Box"]["price_per_base_unit"] == 2.0
        assert by_unit["Tablet"]["price_per_base_unit"] == 2.5


def test_search_medicines_matches_by_name(app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
        make_box_file_medicine(name="Napa Extra")
        results = search_medicines("ceta")
        assert len(results) == 1
        assert results[0]["name"] == "Cetamol"


def test_list_medicines_returns_all(app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
        make_bottled_medicine(name="Cough Syrup")
        assert len(list_medicines()) == 2


def test_count_medicines(app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
        make_bottled_medicine(name="Cough Syrup")
        assert count_medicines() == 2


def test_add_medicine_view_box_file_creates_medicine(admin_client, app):
    resp = admin_client.post("/medicines/add", data={
        "name": "Cetamol",
        "packaging_type": "box_file",
        "tablets_per_file": "20",
        "files_per_box": "12",
        "price_per_box": "480",
        "price_per_file": "45",
        "price_per_tablet": "2.5",
        "low_stock_threshold": "50",
    })
    assert resp.status_code == 302
    with app.app_context():
        assert len(list_medicines()) == 1


def test_add_medicine_view_bottled_other_creates_medicine(admin_client, app):
    resp = admin_client.post("/medicines/add", data={
        "name": "Cough Syrup",
        "packaging_type": "bottled_other",
        "unit_type": "Bottle",
        "unit_price": "120",
        "low_stock_threshold": "5",
    })
    assert resp.status_code == 302
    with app.app_context():
        assert len(list_medicines()) == 1


def test_add_medicine_view_invalid_input_flashes_error_not_500(admin_client):
    resp = admin_client.post("/medicines/add", data={
        "name": "Bad",
        "packaging_type": "box_file",
        "tablets_per_file": "not_a_number",
        "files_per_box": "12",
        "price_per_box": "480",
        "price_per_file": "45",
        "price_per_tablet": "2.5",
        "low_stock_threshold": "50",
    })
    assert resp.status_code == 200
