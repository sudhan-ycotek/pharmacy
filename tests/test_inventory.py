import pytest

from inventory import (
    add_medicine,
    add_stock,
    count_medicines,
    get_batch,
    get_db,
    get_medicine_units,
    list_batches,
    list_medicines,
    low_stock_medicines,
    recent_batches,
    remove_stock,
    search_medicines,
    sellable_units,
    set_medicine_photo,
    unit_price_range,
    update_max_discount,
)
from helpers import make_batch, make_bottled_medicine, make_box_file_medicine


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
            add_medicine("Bad Medicine", "box_file", 10, tablets_per_file=0, files_per_box=12)


def test_add_medicine_bottled_other_requires_unit_name(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "bottled_other", 10, unit_name="")


def test_add_medicine_rejects_out_of_range_max_discount_percent(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "bottled_other", 10, unit_name="Bottle", max_discount_percent=150)
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "bottled_other", 10, unit_name="Bottle", max_discount_percent=-1)


def test_add_stock_converts_to_base_units(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        new_total = add_stock(medicine_id, "Box", 2, "2030-01-01", 1.0, 2.0)
        assert new_total == 480


def test_add_stock_unknown_unit_raises(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Pallet", 1, "2030-01-01", 1.0, 2.0)


def test_add_stock_rejects_fractional_quantity(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Box", 2.5, "2030-01-01", 1.0, 2.0)


def test_add_stock_rejects_past_expiry_date(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Box", 1, "2020-01-01", 1.0, 2.0)


def test_add_stock_rejects_malformed_expiry_date(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Box", 1, "not-a-date", 1.0, 2.0)


def test_add_stock_rejects_negative_cost_or_mrp(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Box", 1, "2030-01-01", -1.0, 2.0)
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Box", 1, "2030-01-01", 1.0, -2.0)


def test_add_stock_merges_into_existing_batch_on_same_expiry_and_cost(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        add_stock(medicine_id, "Box", 2, "2030-01-01", 1.0, 2.0)
        add_stock(medicine_id, "Box", 3, "2030-01-01", 1.0, 2.5)
        batches = list_batches(medicine_id)
        assert len(batches) == 1
        assert batches[0]["quantity_remaining"] == 5 * 240
        assert batches[0]["quantity_received"] == 5 * 240
        # MRP from the second add_stock call wins.
        assert batches[0]["mrp_per_base_unit"] == 2.5


def test_add_stock_creates_new_batch_on_different_cost(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        add_stock(medicine_id, "Box", 2, "2030-01-01", 1.0, 2.0)
        add_stock(medicine_id, "Box", 2, "2030-01-01", 1.5, 2.5)
        batches = list_batches(medicine_id)
        assert len(batches) == 2


def test_add_stock_creates_new_batch_on_different_expiry(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        add_stock(medicine_id, "Box", 2, "2030-01-01", 1.0, 2.0)
        add_stock(medicine_id, "Box", 2, "2031-01-01", 1.0, 2.0)
        batches = list_batches(medicine_id)
        assert len(batches) == 2


def test_remove_stock_converts_to_base_units(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        batch_id = make_batch(medicine_id, "Box", 5, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        new_total = remove_stock(batch_id, "Box", 2)
        assert new_total == 3 * 240


def test_remove_stock_rejects_more_than_available(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        batch_id = make_batch(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        with pytest.raises(ValueError):
            remove_stock(batch_id, "Box", 2)


def test_remove_stock_unknown_unit_raises(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        batch_id = make_batch(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        with pytest.raises(ValueError):
            remove_stock(batch_id, "Pallet", 1)


def test_remove_stock_rejects_fractional_quantity(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        batch_id = make_batch(medicine_id, "Box", 5, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        with pytest.raises(ValueError):
            remove_stock(batch_id, "Box", 2.5)


def test_remove_stock_is_isolated_to_its_own_batch(app):
    """Removing more than one batch has must fail even when a sibling batch of
    the same medicine holds plenty of stock."""
    with app.app_context():
        medicine_id = make_box_file_medicine()
        short_batch = make_batch(medicine_id, "Box", 1, expiry_date="2030-01-01",
                                  cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        make_batch(medicine_id, "Box", 10, expiry_date="2031-01-01",
                   cost_price_per_base_unit=1.5, mrp_per_base_unit=2.5)
        with pytest.raises(ValueError):
            remove_stock(short_batch, "Box", 2)


def test_low_stock_medicines_flags_below_threshold(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(low_stock_threshold=50)
        make_batch(medicine_id, "Tablet", 10, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        low = low_stock_medicines()
        assert any(m["id"] == medicine_id for m in low)


def test_update_max_discount_accepts_valid_range(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        update_max_discount(medicine_id, 15)
        from inventory import get_medicine
        assert get_medicine(medicine_id)["max_discount_percent"] == 15


def test_update_max_discount_rejects_out_of_range(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            update_max_discount(medicine_id, 101)
        with pytest.raises(ValueError):
            update_max_discount(medicine_id, -1)


def test_unit_price_range_with_no_batches_is_none(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        ranges = unit_price_range(medicine_id)
        by_unit = {r["unit_name"]: r for r in ranges}
        assert by_unit["Tablet"]["min_price"] is None
        assert by_unit["Tablet"]["max_price"] is None


def test_unit_price_range_with_one_batch_has_equal_min_and_max(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        make_batch(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        ranges = unit_price_range(medicine_id)
        by_unit = {r["unit_name"]: r for r in ranges}
        assert by_unit["Tablet"]["min_price"] == 2.5
        assert by_unit["Tablet"]["max_price"] == 2.5
        assert by_unit["Box"]["min_price"] == 2.5 * 240


def test_unit_price_range_with_two_batches_spans_min_and_max(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        make_batch(medicine_id, "Tablet", 100, expiry_date="2030-01-01",
                   cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        make_batch(medicine_id, "Tablet", 100, expiry_date="2031-01-01",
                   cost_price_per_base_unit=1.2, mrp_per_base_unit=3.0)
        ranges = unit_price_range(medicine_id)
        by_unit = {r["unit_name"]: r for r in ranges}
        assert by_unit["Tablet"]["min_price"] == 2.5
        assert by_unit["Tablet"]["max_price"] == 3.0


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
        "max_discount_percent": "15",
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
        "max_discount_percent": "10",
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
        "max_discount_percent": "10",
        "low_stock_threshold": "50",
    })
    assert resp.status_code == 200


def test_list_medicines_view_shows_price_range_and_photo(app, client, admin_user):
    """Medicines list renders batch-derived prices and, when present, a photo."""
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol")
        make_batch(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        cough_syrup_id = make_bottled_medicine(name="Cough Syrup", unit_name="Bottle")
        set_medicine_photo(cough_syrup_id, "photos/example.jpg")
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.get("/medicines/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2.50" in body
    assert "No stock priced yet" in body  # Cough Syrup has no batches yet
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
        make_batch(medicine_id, "Box", 3, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.get(f"/medicines/{medicine_id}/add-stock")
    assert resp.status_code == 200
    assert b'"num">720</strong>' in resp.data


def test_add_stock_view_post_add_action_creates_batch(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine()
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/add-stock", data={
        "action": "add",
        "unit_name": "Box",
        "quantity": "2",
        "expiry_date": "2030-01-01",
        "cost_price_per_base_unit": "1.0",
        "mrp_per_base_unit": "2.0",
    })
    assert resp.status_code == 302
    with app.app_context():
        from inventory import get_medicine
        assert get_medicine(medicine_id)["stock_in_base_units"] == 2 * 240


def test_add_stock_view_post_remove_action_reduces_stock(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        batch_id = make_batch(medicine_id, "Box", 5, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/add-stock", data={
        "action": "remove",
        "batch_id": str(batch_id),
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
        batch_id = make_batch(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/add-stock", data={
        "action": "remove",
        "batch_id": str(batch_id),
        "unit_name": "Box",
        "quantity": "2",
    })
    assert resp.status_code == 200
    with app.app_context():
        from inventory import get_medicine
        assert get_medicine(medicine_id)["stock_in_base_units"] == 240


def test_recent_batches_includes_recent_and_excludes_older_than_a_week(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol")
        recent_batch_id = make_batch(medicine_id, "Tablet", 10, expiry_date="2030-01-01",
                                      cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        old_batch_id = make_batch(medicine_id, "Tablet", 5, expiry_date="2031-01-01",
                                   cost_price_per_base_unit=1.2, mrp_per_base_unit=3.0)
        db = get_db()
        db.execute(
            "UPDATE medicine_batches SET created_at = datetime('now', 'localtime', '-10 days') WHERE id = ?",
            (old_batch_id,),
        )
        db.commit()

        recent = recent_batches(days=7)
        ids = {b["id"] for b in recent}
        assert recent_batch_id in ids
        assert old_batch_id not in ids
        by_id = {b["id"]: b for b in recent}
        assert by_id[recent_batch_id]["medicine_name"] == "Cetamol"


def test_add_stock_view_post_update_discount_action(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine()
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/add-stock", data={
        "action": "update_discount",
        "max_discount_percent": "12.5",
    })
    assert resp.status_code == 302
    with app.app_context():
        from inventory import get_medicine
        assert get_medicine(medicine_id)["max_discount_percent"] == 12.5
