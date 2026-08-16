import datetime

import pytest

from inventory import (
    add_medicine,
    add_stock,
    count_medicines,
    daily_stock_received,
    edit_medicine,
    get_db,
    get_medicine,
    get_medicine_units,
    list_medicines,
    list_stock_adjustments,
    list_stock_receipts,
    low_stock_medicines,
    medicine_has_stock_history,
    record_stock_adjustment,
    recent_stock_receipts,
    search_medicines,
    sellable_units,
    set_medicine_photo,
    stock_balance_as_of,
    stock_received_this_month,
    total_stock_units,
    unit_prices,
    update_max_discount,
)
from helpers import make_bottled_medicine, make_box_file_medicine, make_stock


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
        new_total = add_stock(medicine_id, "Box", 2, 1.0, 2.0)
        assert new_total == 480


def test_add_stock_unknown_unit_raises(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Pallet", 1, 1.0, 2.0)


def test_add_stock_rejects_fractional_quantity(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Box", 2.5, 1.0, 2.0)


def test_add_stock_rejects_negative_cost_or_mrp(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Box", 1, -1.0, 2.0)
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Box", 1, 1.0, -2.0)


def test_add_stock_updates_medicines_current_price(app):
    """Cost/MRP on the medicine reflect the most recent restock -- 'last price wins'."""
    with app.app_context():
        medicine_id = make_box_file_medicine()
        add_stock(medicine_id, "Box", 2, 1.0, 2.0)
        add_stock(medicine_id, "Box", 3, 1.5, 2.5)
        from inventory import get_medicine
        medicine = get_medicine(medicine_id)
        assert medicine["cost_price_per_base_unit"] == 1.5
        assert medicine["mrp_per_base_unit"] == 2.5


def test_list_stock_receipts_has_no_vendor_for_manually_added_stock(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        add_stock(medicine_id, "Box", 1, 1.0, 2.0)
        receipt = list_stock_receipts(medicine_id)[0]
        assert receipt["vendor_name"] is None


def test_list_stock_receipts_shows_vendor_name_for_purchase_bill_receipts(app):
    with app.app_context():
        from purchases import create_purchase_bill
        from vendors import add_vendor
        from auth import create_user

        medicine_id = make_box_file_medicine()
        vendor_id = add_vendor("ABC Vendors")
        user_id = create_user("admin1", "pw", "admin")
        create_purchase_bill(user_id, vendor_id, "2026-08-01", [{
            "medicine_id": medicine_id, "unit_name": "Box", "quantity": 1,
            "cost_price_original": 1.0, "cost_currency": "NPR", "mrp_original": 2.0,
        }])
        receipt = list_stock_receipts(medicine_id)[0]
        assert receipt["vendor_name"] == "ABC Vendors"


def test_record_stock_adjustment_decrease_reduces_stock(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        from auth import create_user
        user_id = create_user("admin1", "pw", "admin")
        make_stock(medicine_id, "Box", 5, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        new_total = record_stock_adjustment(medicine_id, "Box", 2, "decrease", "damaged", user_id)
        assert new_total == 3 * 240


def test_record_stock_adjustment_increase_adds_stock(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        from auth import create_user
        user_id = create_user("admin1", "pw", "admin")
        make_stock(medicine_id, "Box", 5, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        new_total = record_stock_adjustment(medicine_id, "Box", 1, "increase", "found", user_id)
        assert new_total == 6 * 240


def test_record_stock_adjustment_rejects_decrease_below_zero_stock(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        from auth import create_user
        user_id = create_user("admin1", "pw", "admin")
        make_stock(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        with pytest.raises(ValueError):
            record_stock_adjustment(medicine_id, "Box", 2, "decrease", "damaged", user_id)


def test_record_stock_adjustment_unknown_unit_raises(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        from auth import create_user
        user_id = create_user("admin1", "pw", "admin")
        make_stock(medicine_id, "Box", 5, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        with pytest.raises(ValueError):
            record_stock_adjustment(medicine_id, "Pallet", 1, "decrease", "damaged", user_id)


def test_record_stock_adjustment_rejects_fractional_quantity(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        from auth import create_user
        user_id = create_user("admin1", "pw", "admin")
        make_stock(medicine_id, "Box", 5, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        with pytest.raises(ValueError):
            record_stock_adjustment(medicine_id, "Box", 2.5, "decrease", "damaged", user_id)


def test_record_stock_adjustment_rejects_invalid_reason(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        from auth import create_user
        user_id = create_user("admin1", "pw", "admin")
        make_stock(medicine_id, "Box", 5, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        with pytest.raises(ValueError):
            record_stock_adjustment(medicine_id, "Box", 1, "decrease", "not_a_reason", user_id)


def test_list_stock_adjustments_reflects_recorded_adjustment(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        from auth import create_user
        user_id = create_user("admin1", "pw", "admin")
        make_stock(medicine_id, "Box", 5, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        record_stock_adjustment(medicine_id, "Box", 2, "decrease", "damaged", user_id, note="crushed in transit")
        adjustments = list_stock_adjustments(medicine_id)
        assert len(adjustments) == 1
        assert adjustments[0]["reason"] == "damaged"
        assert adjustments[0]["base_units_delta"] == -2 * 240
        assert adjustments[0]["note"] == "crushed in transit"


def test_low_stock_medicines_flags_below_threshold(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(low_stock_threshold=50)
        make_stock(medicine_id, "Tablet", 10, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
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


def test_unit_prices_is_none_before_any_restock(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        prices = unit_prices(medicine_id)
        by_unit = {p["unit_name"]: p for p in prices}
        assert by_unit["Tablet"]["price"] is None


def test_unit_prices_reflects_current_price_per_unit(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        make_stock(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        prices = unit_prices(medicine_id)
        by_unit = {p["unit_name"]: p for p in prices}
        assert by_unit["Tablet"]["price"] == 2.5
        assert by_unit["Box"]["price"] == 2.5 * 240


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


def test_list_medicines_view_shows_price_and_photo(app, client, admin_user):
    """Medicines list renders the medicine's current price and, when present, a photo."""
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol")
        make_stock(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        cough_syrup_id = make_bottled_medicine(name="Cough Syrup", unit_name="Bottle")
        set_medicine_photo(cough_syrup_id, "photos/example.jpg")
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.get("/medicines/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2.50" in body
    assert "No stock priced yet" in body  # Cough Syrup has no stock priced yet
    assert "photos/example.jpg" in body


def test_add_stock_view_post_invalid_action_flashes_error(app, client, admin_user):
    """Test that POST with no recognized action re-renders form with flash instead of 500."""
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
        make_stock(medicine_id, "Box", 3, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.get(f"/medicines/{medicine_id}/add-stock")
    assert resp.status_code == 200
    assert b'"num">720</strong>' in resp.data


def test_add_stock_view_post_add_action_no_longer_creates_stock(app, client, admin_user):
    """The old per-medicine 'Add Stock' form is replaced entirely by the vendor
    purchase-bill flow -- posting action=add to this route must no longer add stock."""
    with app.app_context():
        medicine_id = make_box_file_medicine()
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/add-stock", data={
        "action": "add",
        "unit_name": "Box",
        "quantity": "2",
        "cost_price_per_base_unit": "1.0",
        "mrp_per_base_unit": "2.0",
    })
    assert resp.status_code == 200
    with app.app_context():
        from inventory import get_medicine
        assert get_medicine(medicine_id)["stock_in_base_units"] == 0


def test_max_discount_ajax_route_updates_and_returns_json(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine()
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(
        f"/medicines/{medicine_id}/max-discount",
        json={"max_discount_percent": 22.5},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"max_discount_percent": 22.5}
    with app.app_context():
        from inventory import get_medicine
        assert get_medicine(medicine_id)["max_discount_percent"] == 22.5


def test_max_discount_ajax_route_rejects_out_of_range(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine()
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(
        f"/medicines/{medicine_id}/max-discount",
        json={"max_discount_percent": 150},
    )
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_max_discount_ajax_route_requires_admin(app, client, staff_user):
    with app.app_context():
        medicine_id = make_box_file_medicine()
    client.post("/login", data={"username": "staff1", "password": "staffpass"})
    resp = client.post(
        f"/medicines/{medicine_id}/max-discount",
        json={"max_discount_percent": 10},
    )
    assert resp.status_code == 403


def test_add_stock_view_post_adjust_decrease_reduces_stock(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        make_stock(medicine_id, "Box", 5, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/add-stock", data={
        "action": "adjust",
        "direction": "decrease",
        "unit_name": "Box",
        "quantity": "2",
        "reason": "damaged",
    })
    assert resp.status_code == 302
    with app.app_context():
        from inventory import get_medicine
        assert get_medicine(medicine_id)["stock_in_base_units"] == 3 * 240


def test_add_stock_view_post_adjust_decrease_more_than_available_flashes_error(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        make_stock(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/add-stock", data={
        "action": "adjust",
        "direction": "decrease",
        "unit_name": "Box",
        "quantity": "2",
        "reason": "damaged",
    })
    assert resp.status_code == 200
    with app.app_context():
        from inventory import get_medicine
        assert get_medicine(medicine_id)["stock_in_base_units"] == 240


def test_recent_stock_receipts_includes_recent_and_excludes_older_than_a_week(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol")
        db = get_db()
        make_stock(medicine_id, "Tablet", 10, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        recent_id = db.execute(
            "SELECT id FROM stock_receipts WHERE medicine_id = ?", (medicine_id,)
        ).fetchone()["id"]
        make_stock(medicine_id, "Tablet", 5, cost_price_per_base_unit=1.2, mrp_per_base_unit=3.0)
        old_id = db.execute(
            "SELECT id FROM stock_receipts WHERE medicine_id = ? AND id != ?", (medicine_id, recent_id)
        ).fetchone()["id"]
        db.execute(
            "UPDATE stock_receipts SET created_at = datetime('now', 'localtime', '-10 days') WHERE id = ?",
            (old_id,),
        )
        db.commit()

        recent = recent_stock_receipts(days=7)
        ids = {r["id"] for r in recent}
        assert recent_id in ids
        assert old_id not in ids
        by_id = {r["id"]: r for r in recent}
        assert by_id[recent_id]["medicine_name"] == "Cetamol"


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


def test_daily_stock_received_groups_by_day(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        db = get_db()
        make_stock(medicine_id, "Box", 2, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        today_id = db.execute(
            "SELECT id FROM stock_receipts WHERE medicine_id = ?", (medicine_id,)
        ).fetchone()["id"]
        make_stock(medicine_id, "Box", 3, cost_price_per_base_unit=1.5, mrp_per_base_unit=2.5)
        old_id = db.execute(
            "SELECT id FROM stock_receipts WHERE medicine_id = ? AND id != ?", (medicine_id, today_id)
        ).fetchone()["id"]
        db.execute(
            "UPDATE stock_receipts SET created_at = datetime('now', 'localtime', '-3 days') WHERE id = ?",
            (old_id,),
        )
        db.commit()

        rows = daily_stock_received(days=7)
        by_day = {r["day"]: r["received"] for r in rows}
        assert len(by_day) == 2
        assert sorted(by_day.values()) == [2 * 240, 3 * 240]


def test_daily_stock_received_excludes_days_outside_window(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        db = get_db()
        make_stock(medicine_id, "Box", 2, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        old_id = db.execute(
            "SELECT id FROM stock_receipts WHERE medicine_id = ?", (medicine_id,)
        ).fetchone()["id"]
        db.execute(
            "UPDATE stock_receipts SET created_at = datetime('now', 'localtime', '-30 days') WHERE id = ?",
            (old_id,),
        )
        db.commit()

        rows = daily_stock_received(days=7)
        assert rows == []


def test_total_stock_units_sums_across_medicines(app):
    with app.app_context():
        m1 = make_box_file_medicine(name="Cetamol")
        m2 = make_box_file_medicine(name="Napa")
        make_stock(m1, "Box", 2, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        make_stock(m2, "Box", 3, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        assert total_stock_units() == (2 + 3) * 240


def test_total_stock_units_zero_when_no_medicines(app):
    with app.app_context():
        assert total_stock_units() == 0


def test_stock_received_this_month_excludes_prior_month(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        db = get_db()
        make_stock(medicine_id, "Box", 2, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        this_month_id = db.execute(
            "SELECT id FROM stock_receipts WHERE medicine_id = ?", (medicine_id,)
        ).fetchone()["id"]
        make_stock(medicine_id, "Box", 5, cost_price_per_base_unit=1.5, mrp_per_base_unit=2.5)
        last_month_id = db.execute(
            "SELECT id FROM stock_receipts WHERE medicine_id = ? AND id != ?", (medicine_id, this_month_id)
        ).fetchone()["id"]
        db.execute(
            "UPDATE stock_receipts SET created_at = datetime('now', 'localtime', 'start of month', '-1 day') "
            "WHERE id = ?",
            (last_month_id,),
        )
        db.commit()

        assert stock_received_this_month() == 2 * 240


def test_low_stock_medicines_includes_last_restock_timestamp(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(low_stock_threshold=100)
        make_stock(medicine_id, "Tablet", 10, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        low = {m["id"]: m for m in low_stock_medicines()}
        assert low[medicine_id]["last_restock"] is not None


def test_low_stock_medicines_last_restock_none_when_never_restocked(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(low_stock_threshold=100)
        low = {m["id"]: m for m in low_stock_medicines()}
        assert low[medicine_id]["last_restock"] is None


# --- company linkage + packing ------------------------------------------

def test_add_medicine_stores_company_and_packing(app):
    with app.app_context():
        from companies import add_company

        company_id = add_company("Cipla Nepal")
        medicine_id = add_medicine(
            "Cetamol", "box_file", 10, tablets_per_file=20, files_per_box=12,
            company_id=company_id, packing="10x10 blister",
        )
        medicine = get_medicine(medicine_id)
        assert medicine["company_id"] == company_id
        assert medicine["packing"] == "10x10 blister"


def test_add_medicine_company_and_packing_are_optional(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        medicine = get_medicine(medicine_id)
        assert medicine["company_id"] is None
        assert medicine["packing"] is None


def test_add_medicine_rejects_unknown_company_id(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Cetamol", "box_file", 10, tablets_per_file=20, files_per_box=12, company_id=999)


def test_add_medicine_assigns_sequential_med_codes(app):
    with app.app_context():
        id1 = make_box_file_medicine(name="Cetamol")
        id2 = make_box_file_medicine(name="Paracetamol")
        assert get_medicine(id1)["code"] == "MED-0001"
        assert get_medicine(id2)["code"] == "MED-0002"


def test_add_medicine_code_overflows_past_9999_rather_than_blocking(app):
    with app.app_context():
        from db import get_db

        db = get_db()
        db.execute(
            "INSERT INTO medicines (code, name, packaging_type) VALUES (?, ?, ?)",
            ("MED-9999", "Medicine 9999", "bottled_other"),
        )
        medicine_id = make_bottled_medicine(name="Medicine 10000")
        assert get_medicine(medicine_id)["code"] == "MED-10000"


def test_list_medicines_includes_company_name_via_join(app):
    with app.app_context():
        from companies import add_company

        company_id = add_company("Cipla Nepal")
        add_medicine("Cetamol", "box_file", 10, tablets_per_file=20, files_per_box=12, company_id=company_id)
        make_bottled_medicine(name="Cough Syrup")
        by_name = {m["name"]: m for m in list_medicines()}
        assert by_name["Cetamol"]["company_name"] == "Cipla Nepal"
        assert by_name["Cough Syrup"]["company_name"] is None


# --- medicine_has_stock_history ------------------------------------------

def test_medicine_has_stock_history_false_for_brand_new_medicine(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        assert medicine_has_stock_history(medicine_id) is False


def test_medicine_has_stock_history_true_after_stock_receipt(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        make_stock(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        assert medicine_has_stock_history(medicine_id) is True


def test_medicine_has_stock_history_true_after_stock_adjustment(app):
    with app.app_context():
        from auth import create_user

        medicine_id = make_box_file_medicine()
        user_id = create_user("admin1", "pw", "admin")
        # An adjustment alone (no prior receipt) can only increase stock.
        record_stock_adjustment(medicine_id, "Box", 1, "increase", "found", user_id)
        assert medicine_has_stock_history(medicine_id) is True


def test_medicine_has_stock_history_true_after_sale_even_at_zero_stock(app):
    """A medicine sold down to zero must still count as having history --
    locking is based on historical rows existing, not current stock level."""
    with app.app_context():
        from auth import create_user
        from sales import create_sale

        medicine_id = make_box_file_medicine(tablets_per_file=20, files_per_box=12)
        make_stock(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        user_id = create_user("cashier", "pw", "staff")
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 240}])

        assert get_medicine(medicine_id)["stock_in_base_units"] == 0
        assert medicine_has_stock_history(medicine_id) is True


# --- edit_medicine --------------------------------------------------------

def test_edit_medicine_raises_for_unknown_medicine(app):
    with app.app_context():
        with pytest.raises(ValueError):
            edit_medicine(999, "New Name", "box_file", 10, tablets_per_file=20, files_per_box=12)


def test_edit_medicine_updates_name_company_packing_threshold_discount_photo(app):
    with app.app_context():
        from companies import add_company

        medicine_id = make_box_file_medicine(name="Cetamol", low_stock_threshold=10, max_discount_percent=0)
        company_id = add_company("Cipla Nepal")

        edit_medicine(
            medicine_id, "Cetamol Forte", "box_file", 25, max_discount_percent=15,
            photo_path="photos/new.jpg", tablets_per_file=20, files_per_box=12,
            company_id=company_id, packing="10x10 blister",
        )

        medicine = get_medicine(medicine_id)
        assert medicine["name"] == "Cetamol Forte"
        assert medicine["low_stock_threshold"] == 25
        assert medicine["max_discount_percent"] == 15
        assert medicine["photo_path"] == "photos/new.jpg"
        assert medicine["company_id"] == company_id
        assert medicine["packing"] == "10x10 blister"


def test_edit_medicine_rejects_unknown_company_id(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            edit_medicine(medicine_id, "Cetamol", "box_file", 10, tablets_per_file=20, files_per_box=12,
                           company_id=999)


def test_edit_medicine_allows_packaging_change_when_no_stock_history(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(tablets_per_file=20, files_per_box=12)
        edit_medicine(medicine_id, "Cetamol", "box_file", 10, tablets_per_file=10, files_per_box=6)
        units = {u["unit_name"]: u for u in get_medicine_units(medicine_id)}
        assert units["File"]["qty_in_base_units"] == 10
        assert units["Box"]["qty_in_base_units"] == 60


def test_edit_medicine_allows_switching_packaging_type_when_no_stock_history(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        edit_medicine(medicine_id, "Cough Syrup", "bottled_other", 5, unit_name="Bottle")
        medicine = get_medicine(medicine_id)
        assert medicine["packaging_type"] == "bottled_other"
        units = get_medicine_units(medicine_id)
        assert len(units) == 1
        assert units[0]["unit_name"] == "Bottle"


def test_edit_medicine_rejects_packaging_type_change_after_stock_receipt(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        make_stock(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        with pytest.raises(ValueError):
            edit_medicine(medicine_id, "Cough Syrup", "bottled_other", 5, unit_name="Bottle")


def test_edit_medicine_rejects_ratio_change_after_stock_receipt(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(tablets_per_file=20, files_per_box=12)
        make_stock(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        with pytest.raises(ValueError):
            edit_medicine(medicine_id, "Cetamol", "box_file", 10, tablets_per_file=10, files_per_box=12)


def test_edit_medicine_rejects_unit_name_change_after_stock_receipt(app):
    with app.app_context():
        medicine_id = make_bottled_medicine(unit_name="Bottle")
        make_stock(medicine_id, "Bottle", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        with pytest.raises(ValueError):
            edit_medicine(medicine_id, "Cough Syrup", "bottled_other", 5, unit_name="Tube")


def test_edit_medicine_allows_non_packaging_changes_after_stock_receipt(app):
    """Locking only blocks packaging_type/ratio changes -- name/threshold/discount/
    company/packing must remain editable even once stock history exists."""
    with app.app_context():
        medicine_id = make_box_file_medicine(tablets_per_file=20, files_per_box=12)
        make_stock(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        edit_medicine(
            medicine_id, "Cetamol Forte", "box_file", 30, max_discount_percent=10,
            tablets_per_file=20, files_per_box=12, packing="10x10 blister",
        )
        medicine = get_medicine(medicine_id)
        assert medicine["name"] == "Cetamol Forte"
        assert medicine["low_stock_threshold"] == 30
        assert medicine["max_discount_percent"] == 10
        assert medicine["packing"] == "10x10 blister"


def test_edit_medicine_rejects_ratio_change_after_stock_adjustment_only(app):
    with app.app_context():
        from auth import create_user

        medicine_id = make_box_file_medicine(tablets_per_file=20, files_per_box=12)
        user_id = create_user("admin1", "pw", "admin")
        record_stock_adjustment(medicine_id, "Box", 1, "increase", "found", user_id)
        with pytest.raises(ValueError):
            edit_medicine(medicine_id, "Cetamol", "box_file", 10, tablets_per_file=10, files_per_box=12)


def test_edit_medicine_stays_locked_after_medicine_sold_down_to_zero_stock(app):
    """The key locking scenario: a medicine that was sold down to zero current
    stock must still reject a packaging/ratio change, because the lock is
    based on historical rows existing, not on current stock_in_base_units."""
    with app.app_context():
        from auth import create_user
        from sales import create_sale

        medicine_id = make_box_file_medicine(tablets_per_file=20, files_per_box=12)
        make_stock(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        user_id = create_user("cashier", "pw", "staff")
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 240}])
        assert get_medicine(medicine_id)["stock_in_base_units"] == 0

        with pytest.raises(ValueError):
            edit_medicine(medicine_id, "Cetamol", "box_file", 10, tablets_per_file=10, files_per_box=12)
        with pytest.raises(ValueError):
            edit_medicine(medicine_id, "Cough Syrup", "bottled_other", 10, unit_name="Bottle")

        # But the medicine's stock level itself is unaffected by the rejection.
        assert get_medicine(medicine_id)["stock_in_base_units"] == 0


# --- edit route -------------------------------------------------------

def test_edit_medicine_view_get_renders_form(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol")
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.get(f"/medicines/{medicine_id}/edit")
    assert resp.status_code == 200
    assert b"Cetamol" in resp.data


def test_edit_medicine_view_get_404_for_unknown_medicine(app, client, admin_user):
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.get("/medicines/999/edit")
    assert resp.status_code == 404


def test_edit_medicine_view_requires_admin(app, client, staff_user):
    with app.app_context():
        medicine_id = make_box_file_medicine()
    client.post("/login", data={"username": "staff1", "password": "staffpass"})
    resp = client.get(f"/medicines/{medicine_id}/edit")
    assert resp.status_code == 403


def test_edit_medicine_view_post_updates_medicine(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol")
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/edit", data={
        "name": "Cetamol Forte",
        "packaging_type": "box_file",
        "tablets_per_file": "20",
        "files_per_box": "12",
        "low_stock_threshold": "30",
        "max_discount_percent": "12",
        "packing": "10x10 blister",
    })
    assert resp.status_code == 302
    with app.app_context():
        medicine = get_medicine(medicine_id)
        assert medicine["name"] == "Cetamol Forte"
        assert medicine["low_stock_threshold"] == 30
        assert medicine["packing"] == "10x10 blister"


def test_edit_medicine_view_post_rejects_packaging_change_after_stock_history(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol", tablets_per_file=20, files_per_box=12)
        make_stock(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.post(f"/medicines/{medicine_id}/edit", data={
        "name": "Cetamol",
        "packaging_type": "box_file",
        "tablets_per_file": "10",
        "files_per_box": "12",
        "low_stock_threshold": "10",
        "max_discount_percent": "0",
    })
    # Re-renders the form with a flash instead of a 500 or a silent success.
    assert resp.status_code == 200
    with app.app_context():
        units = {u["unit_name"]: u for u in get_medicine_units(medicine_id)}
        assert units["File"]["qty_in_base_units"] == 20


# --- stock_balance_as_of ---------------------------------------------------

def test_stock_balance_as_of_today_matches_live_counter_for_mixed_activity(app):
    """The core invariant: reconstructing today's balance from every stock-moving
    table (receipts, adjustments, purchase returns, sales, sale returns) must land
    on exactly the same number as medicines.stock_in_base_units -- a much stronger
    check than hand-computing an expected total."""
    with app.app_context():
        from auth import create_user
        from purchases import create_purchase_bill, create_purchase_return
        from sales import create_sale, create_sale_return, get_sale
        from vendors import add_vendor

        user_id = create_user("admin1", "pw", "admin")
        vendor_id = add_vendor("ABC Vendors")

        medicine_id = make_box_file_medicine(name="Cetamol", tablets_per_file=20, files_per_box=12)
        # A second medicine with zero activity -- must still show up (at balance 0)
        # via the LEFT JOIN onto medicines.
        untouched_id = make_bottled_medicine(name="Cough Syrup")

        # Manual restock, then a damage adjustment.
        add_stock(medicine_id, "Box", 10, 1.0, 2.0)  # +2400 base units
        record_stock_adjustment(medicine_id, "Box", 2, "decrease", "damaged", user_id)  # -480

        # A vendor purchase, then a partial purchase return.
        bill = create_purchase_bill(user_id, vendor_id, "2026-08-01", [{
            "medicine_id": medicine_id, "unit_name": "Box", "quantity": 5,
            "cost_price_original": 1.0, "mrp_original": 2.0,
        }])  # +1200
        create_purchase_return(
            bill["purchase_bill_id"],
            [{"medicine_id": medicine_id, "unit_name": "Box", "quantity": 1}],
            "damaged", user_id,
        )  # -240

        # A sale, then a partial sale return.
        sale = create_sale(user_id, [
            {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 100},
        ])  # -100
        sale_item_id = get_sale(sale["sale_id"])["items"][0]["id"]
        create_sale_return(
            sale["sale_id"], [{"sale_item_id": sale_item_id, "quantity": 20}], "wrong_item", user_id,
        )  # +20

        live_balance = get_medicine(medicine_id)["stock_in_base_units"]
        today = datetime.date.today().isoformat()
        rows = {r["medicine_id"]: r for r in stock_balance_as_of(today)}

        assert rows[medicine_id]["balance"] == live_balance
        assert rows[untouched_id]["balance"] == 0


def test_stock_balance_as_of_excludes_activity_after_the_as_of_date(app):
    """Backdate one receipt into the past via raw SQL, add a second receipt dated
    'today', then confirm an as-of date before the backdated receipt shows a lower
    (zero) balance, a date between the two includes only the backdated one, and
    'today' includes both -- proving later activity is excluded relative to the
    chosen as-of date, not just relative to a rolling window."""
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol", tablets_per_file=20, files_per_box=12)
        make_stock(medicine_id, "Box", 3, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        db = get_db()
        backdated_id = db.execute(
            "SELECT id FROM stock_receipts WHERE medicine_id = ?", (medicine_id,)
        ).fetchone()["id"]
        db.execute(
            "UPDATE stock_receipts SET created_at = datetime('now', 'localtime', '-10 days') WHERE id = ?",
            (backdated_id,),
        )
        db.commit()

        # The later activity that must be excluded by an earlier as-of date.
        make_stock(medicine_id, "Box", 2, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)

        as_of_before = (datetime.date.today() - datetime.timedelta(days=20)).isoformat()
        as_of_between = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
        as_of_today = datetime.date.today().isoformat()

        def balance(as_of):
            rows = {r["medicine_id"]: r for r in stock_balance_as_of(as_of)}
            return rows[medicine_id]["balance"]

        assert balance(as_of_before) == 0
        assert balance(as_of_between) == 3 * 240
        assert balance(as_of_today) == 5 * 240


def test_stock_balance_as_of_excludes_voided_sale(app):
    with app.app_context():
        from auth import create_user
        from sales import create_sale, void_sale

        user_id = create_user("cashier", "pw", "staff")
        medicine_id = make_box_file_medicine(name="Cetamol", tablets_per_file=20, files_per_box=12)
        make_stock(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)

        sale = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 30}])
        today = datetime.date.today().isoformat()
        rows = {r["medicine_id"]: r for r in stock_balance_as_of(today)}
        assert rows[medicine_id]["balance"] == 70  # 100 - 30

        void_sale(sale["sale_id"])
        rows = {r["medicine_id"]: r for r in stock_balance_as_of(today)}
        # The sale_items row still exists in the database -- it must be excluded
        # via sales.voided = 0, not by the row disappearing.
        assert rows[medicine_id]["balance"] == 100
        assert rows[medicine_id]["balance"] == get_medicine(medicine_id)["stock_in_base_units"]


def test_stock_balance_as_of_excludes_voided_purchase_return(app):
    with app.app_context():
        from auth import create_user
        from purchases import create_purchase_bill, create_purchase_return, void_purchase_return
        from vendors import add_vendor

        user_id = create_user("admin1", "pw", "admin")
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol", tablets_per_file=20, files_per_box=12)
        bill = create_purchase_bill(user_id, vendor_id, "2026-08-01", [{
            "medicine_id": medicine_id, "unit_name": "Box", "quantity": 5,
            "cost_price_original": 1.0, "mrp_original": 2.0,
        }])
        ret = create_purchase_return(
            bill["purchase_bill_id"],
            [{"medicine_id": medicine_id, "unit_name": "Box", "quantity": 2}],
            "damaged", user_id,
        )
        today = datetime.date.today().isoformat()
        rows = {r["medicine_id"]: r for r in stock_balance_as_of(today)}
        assert rows[medicine_id]["balance"] == 3 * 240  # 5 received - 2 returned

        void_purchase_return(ret["purchase_return_id"])
        rows = {r["medicine_id"]: r for r in stock_balance_as_of(today)}
        # The purchase_return_items row still exists -- excluded via
        # purchase_returns.voided = 0, not by deletion.
        assert rows[medicine_id]["balance"] == 5 * 240
        assert rows[medicine_id]["balance"] == get_medicine(medicine_id)["stock_in_base_units"]


def test_stock_balance_as_of_excludes_voided_sale_return(app):
    with app.app_context():
        from auth import create_user
        from sales import create_sale, create_sale_return, get_sale, void_sale_return

        user_id = create_user("cashier", "pw", "staff")
        medicine_id = make_box_file_medicine(name="Cetamol", tablets_per_file=20, files_per_box=12)
        make_stock(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)

        sale = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 30}])
        sale_item_id = get_sale(sale["sale_id"])["items"][0]["id"]
        ret = create_sale_return(
            sale["sale_id"], [{"sale_item_id": sale_item_id, "quantity": 10}], "wrong_item", user_id,
        )
        today = datetime.date.today().isoformat()
        rows = {r["medicine_id"]: r for r in stock_balance_as_of(today)}
        assert rows[medicine_id]["balance"] == 80  # 100 - 30 + 10

        void_sale_return(ret["sale_return_id"])
        rows = {r["medicine_id"]: r for r in stock_balance_as_of(today)}
        # The sale_return_items row still exists -- excluded via
        # sale_returns.voided = 0, not by deletion.
        assert rows[medicine_id]["balance"] == 70
        assert rows[medicine_id]["balance"] == get_medicine(medicine_id)["stock_in_base_units"]


def test_stock_balance_as_of_cost_vs_mrp_value_switching(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol", tablets_per_file=20, files_per_box=12)
        make_stock(medicine_id, "Box", 2, cost_price_per_base_unit=1.5, mrp_per_base_unit=3.0)
        today = datetime.date.today().isoformat()

        cost_rows = {r["medicine_id"]: r for r in stock_balance_as_of(today, price_basis="cost")}
        mrp_rows = {r["medicine_id"]: r for r in stock_balance_as_of(today, price_basis="mrp")}

        balance = 2 * 240
        assert cost_rows[medicine_id]["unit_price"] == 1.5
        assert cost_rows[medicine_id]["value"] == balance * 1.5
        assert mrp_rows[medicine_id]["unit_price"] == 3.0
        assert mrp_rows[medicine_id]["value"] == balance * 3.0


def test_stock_balance_as_of_rejects_invalid_price_basis(app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
        with pytest.raises(ValueError):
            stock_balance_as_of(datetime.date.today().isoformat(), price_basis="retail")


# --- stock_balance_view route -----------------------------------------------

def test_stock_balance_view_requires_admin(app, client, staff_user):
    client.post("/login", data={"username": "staff1", "password": "staffpass"})
    resp = client.get("/medicines/stock-balance")
    assert resp.status_code == 403


def test_stock_balance_view_renders_for_admin(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol", tablets_per_file=20, files_per_box=12)
        make_stock(medicine_id, "Box", 2, cost_price_per_base_unit=1.5, mrp_per_base_unit=3.0)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.get("/medicines/stock-balance")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Cetamol" in body
    assert "Upto Date" in body


def test_stock_balance_view_defaults_to_today(app, client, admin_user):
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.get("/medicines/stock-balance")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert datetime.date.today().isoformat() in body


def test_stock_balance_view_mrp_toggle_changes_value_shown(app, client, admin_user):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol", tablets_per_file=20, files_per_box=12)
        make_stock(medicine_id, "Box", 1, cost_price_per_base_unit=1.0, mrp_per_base_unit=5.0)
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    resp = client.get("/medicines/stock-balance", query_string={"price_basis": "mrp"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # 240 base units at MRP 5.0/base unit = 1200.00
    assert "1200.00" in body
