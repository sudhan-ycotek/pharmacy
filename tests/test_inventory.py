import pytest

from inventory import (
    add_medicine,
    add_stock,
    get_medicine_units,
    list_medicines,
    low_stock_medicines,
    search_medicines,
    unit_price_breakdown,
)

TABLET_UNITS = [
    {"unit_name": "Box", "qty_in_base_units": 240, "price": 480.0},
    {"unit_name": "File", "qty_in_base_units": 20, "price": 45.0},
    {"unit_name": "Tablet", "qty_in_base_units": 1, "price": 2.5},
]

LIQUID_UNITS = [
    {"unit_name": "Bottle", "qty_in_base_units": 1, "price": 120.0},
]


def test_add_medicine_requires_exactly_one_base_unit(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "Tablet", 10, [
                {"unit_name": "Box", "qty_in_base_units": 240, "price": 480.0},
            ])


def test_add_medicine_with_multi_level_units(app):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        units = get_medicine_units(medicine_id)
        assert [u["unit_name"] for u in units] == ["Tablet", "File", "Box"]


def test_add_medicine_with_single_unit(app):
    with app.app_context():
        medicine_id = add_medicine("Cough Syrup", "Liquid", 5, LIQUID_UNITS)
        units = get_medicine_units(medicine_id)
        assert len(units) == 1
        assert units[0]["unit_name"] == "Bottle"


def test_add_stock_converts_to_base_units(app):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        new_total = add_stock(medicine_id, "Box", 2)
        assert new_total == 480


def test_add_stock_unknown_unit_raises(app):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Pallet", 1)


def test_low_stock_medicines_flags_below_threshold(app):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        add_stock(medicine_id, "Tablet", 10)
        low = low_stock_medicines()
        assert any(m["id"] == medicine_id for m in low)


def test_unit_price_breakdown_computes_price_per_base_unit(app):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        breakdown = unit_price_breakdown(medicine_id)
        by_unit = {b["unit_name"]: b for b in breakdown}
        assert by_unit["Box"]["price_per_base_unit"] == 2.0
        assert by_unit["Tablet"]["price_per_base_unit"] == 2.5


def test_search_medicines_matches_by_name(app):
    with app.app_context():
        add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        add_medicine("Napa Extra", "Tablet", 50, TABLET_UNITS)
        results = search_medicines("ceta")
        assert len(results) == 1
        assert results[0]["name"] == "Cetamol"


def test_list_medicines_returns_all(app):
    with app.app_context():
        add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        add_medicine("Cough Syrup", "Liquid", 5, LIQUID_UNITS)
        assert len(list_medicines()) == 2


def test_add_medicine_rejects_negative_qty_in_base_units(app):
    with app.app_context():
        with pytest.raises(ValueError, match="qty_in_base_units >= 1"):
            add_medicine("Bad Medicine", "Tablet", 10, [
                {"unit_name": "Tablet", "qty_in_base_units": -5, "price": 2.5},
            ])


def test_add_medicine_rejects_zero_qty_in_base_units(app):
    with app.app_context():
        with pytest.raises(ValueError, match="qty_in_base_units >= 1"):
            add_medicine("Bad Medicine", "Tablet", 10, [
                {"unit_name": "Tablet", "qty_in_base_units": 0, "price": 2.5},
            ])


def test_add_medicine_rejects_negative_price(app):
    with app.app_context():
        with pytest.raises(ValueError, match="price cannot be negative"):
            add_medicine("Bad Medicine", "Tablet", 10, [
                {"unit_name": "Tablet", "qty_in_base_units": 1, "price": -2.5},
            ])


def test_add_medicine_view_post_invalid_unit_qty_flashes_error(app, client, admin_user):
    """Test that POST with invalid unit qty re-renders form with flash instead of 500."""
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post("/medicines/add", data={
        "name": "Test Medicine",
        "category": "Tablet",
        "low_stock_threshold": "10",
        "unit_name": "Tablet",
        "unit_qty": "invalid_number",
        "unit_price": "2.5",
    })
    # Should re-render form (200) not error (500)
    assert resp.status_code == 200


def test_add_medicine_view_post_negative_qty_flashes_error(app, client, admin_user):
    """Test that POST with negative qty_in_base_units flashes error."""
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post("/medicines/add", data={
        "name": "Test Medicine",
        "category": "Tablet",
        "low_stock_threshold": "10",
        "unit_name": "Tablet",
        "unit_qty": "-5",
        "unit_price": "2.5",
    })
    # Should re-render form (200) not error (500)
    assert resp.status_code == 200


def test_add_stock_view_post_invalid_quantity_flashes_error(app, client, admin_user):
    """Test that POST with invalid quantity re-renders form with flash instead of 500."""
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/add-stock", data={
        "unit_name": "Tablet",
        "quantity": "invalid_number",
    })
    # Should re-render form (200) not error (500)
    assert resp.status_code == 200
