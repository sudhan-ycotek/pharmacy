import pytest

from inventory import (
    add_medicine,
    add_stock,
    count_medicines,
    get_medicine_units,
    list_medicines,
    low_stock_medicines,
    remove_stock,
    search_medicines,
    sellable_units,
    set_medicine_photo,
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


def test_remove_stock_converts_to_base_units(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        add_stock(medicine_id, "Box", 5)
        new_total = remove_stock(medicine_id, "Box", 2)
        assert new_total == 3 * 240


def test_remove_stock_rejects_more_than_available(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        add_stock(medicine_id, "Box", 1)
        with pytest.raises(ValueError):
            remove_stock(medicine_id, "Box", 2)


def test_remove_stock_unknown_unit_raises(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            remove_stock(medicine_id, "Pallet", 1)


def test_remove_stock_rejects_fractional_quantity(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        add_stock(medicine_id, "Box", 5)
        with pytest.raises(ValueError):
            remove_stock(medicine_id, "Box", 2.5)


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


def test_list_medicines_view_shows_price_breakdown_and_photo(app, client, admin_user):
    """Medicines list renders unit price breakdowns and, when present, a photo."""
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
        make_bottled_medicine(name="Cough Syrup", unit_name="Bottle", unit_price=120.0)
        # attach a photo directly for this test — no need to go through the QR flow
        cough_syrup_id = next(m["id"] for m in list_medicines() if m["name"] == "Cough Syrup")
        set_medicine_photo(cough_syrup_id, "photos/example.jpg")
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.get("/medicines/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2.50" in body  # Tablet unit price from make_box_file_medicine's defaults
    assert "photos/example.jpg" in body


def test_add_stock_view_post_invalid_quantity_flashes_error(app, client, admin_user):
    """Test that POST with invalid quantity re-renders form with flash instead of 500."""
    with app.app_context():
        medicine_id = make_box_file_medicine()
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/add-stock", data={
        "unit_name": "Tablet",
        "quantity": "invalid_number",
    })
    # Should re-render form (200) not error (500)
    assert resp.status_code == 200


def test_add_stock_view_shows_current_stock(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        add_stock(medicine_id, "Box", 3)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.get(f"/medicines/{medicine_id}/add-stock")
    assert resp.status_code == 200
    assert b'"num">720</strong>' in resp.data


def test_add_stock_view_post_remove_action_reduces_stock(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        add_stock(medicine_id, "Box", 5)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/add-stock", data={
        "action": "remove",
        "unit_name": "Box",
        "quantity": "2",
    })
    assert resp.status_code == 302
    with app.app_context():
        from inventory import get_medicine
        assert get_medicine(medicine_id)["stock_in_base_units"] == 3 * 240


def test_add_stock_view_post_remove_more_than_available_flashes_error(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        add_stock(medicine_id, "Box", 1)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/add-stock", data={
        "action": "remove",
        "unit_name": "Box",
        "quantity": "2",
    })
    assert resp.status_code == 200
    with app.app_context():
        from inventory import get_medicine
        assert get_medicine(medicine_id)["stock_in_base_units"] == 240
