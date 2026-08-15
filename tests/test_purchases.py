import io
import json

import pytest

from inventory import get_medicine, list_batches
from purchases import (
    bill_total_paid,
    convert_to_npr,
    create_purchase_bill,
    get_purchase_bill,
    list_batches_for_bill,
    list_payments,
    list_purchase_bills,
    record_payment,
    search_medicines_for_purchase,
    vendor_balance,
)
from vendors import add_vendor
from helpers import make_box_file_medicine


def _cetamol_item(quantity=2, unit_name="Box", expiry_date="2030-01-01",
                   cost_price_original=1.0, cost_currency="NPR", mrp_per_base_unit=2.0,
                   max_discount_percent=None):
    return {
        "unit_name": unit_name, "quantity": quantity, "expiry_date": expiry_date,
        "cost_price_original": cost_price_original, "cost_currency": cost_currency,
        "mrp_per_base_unit": mrp_per_base_unit, "max_discount_percent": max_discount_percent,
    }


# --- convert_to_npr -----------------------------------------------------

def test_convert_to_npr_returns_amount_unchanged_for_npr():
    assert convert_to_npr(100, "NPR") == 100.0


def test_convert_to_npr_multiplies_by_fixed_rate_for_inr():
    assert convert_to_npr(100, "INR") == 160.0


def test_convert_to_npr_rejects_unknown_currency():
    with pytest.raises(ValueError):
        convert_to_npr(100, "USD")


def test_convert_to_npr_rejects_negative_amount():
    with pytest.raises(ValueError):
        convert_to_npr(-1, "NPR")


# --- create_purchase_bill ------------------------------------------------

def test_create_purchase_bill_creates_one_batch_per_item(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        cetamol_id = make_box_file_medicine(name="Cetamol")
        pantop_id = make_box_file_medicine(name="Pantop")
        user_id = _make_admin(app)

        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(), medicine_id=cetamol_id),
            dict(_cetamol_item(quantity=1), medicine_id=pantop_id),
        ])

        assert len(list_batches(cetamol_id)) == 1
        assert len(list_batches(pantop_id)) == 1
        batch = list_batches(cetamol_id)[0]
        assert batch["purchase_bill_id"] == result["purchase_bill_id"]
        assert batch["quantity_received"] == 2 * 240


def test_create_purchase_bill_converts_inr_cost_and_keeps_original(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)

        create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(cost_price_original=10.0, cost_currency="INR"), medicine_id=medicine_id),
        ])

        batch = list_batches(medicine_id)[0]
        assert batch["cost_currency"] == "INR"
        assert batch["cost_price_original"] == 10.0
        assert batch["cost_price_per_base_unit"] == 16.0  # 10 INR * 1.60


def test_create_purchase_bill_computes_total_amount_as_sum_of_items(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)

        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=2, cost_price_original=1.0), medicine_id=medicine_id),
        ])

        # 2 boxes = 480 base units at 1.0/base unit = 480.0
        assert result["total_amount"] == 480.0


def test_create_purchase_bill_rejects_unknown_vendor(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        with pytest.raises(ValueError):
            create_purchase_bill(user_id, 999, "2026-08-01", [
                dict(_cetamol_item(), medicine_id=medicine_id),
            ])


def test_create_purchase_bill_rejects_empty_items(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        user_id = _make_admin(app)
        with pytest.raises(ValueError):
            create_purchase_bill(user_id, vendor_id, "2026-08-01", [])


def test_create_purchase_bill_is_atomic_on_invalid_item(app):
    """One bad line item must not leave earlier valid items partially committed."""
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)

        with pytest.raises(ValueError):
            create_purchase_bill(user_id, vendor_id, "2026-08-01", [
                dict(_cetamol_item(), medicine_id=medicine_id),
                dict(_cetamol_item(unit_name="Pallet"), medicine_id=medicine_id),
            ])

        assert list_batches(medicine_id) == []
        assert get_medicine(medicine_id)["stock_in_base_units"] == 0


def test_create_purchase_bill_records_first_payment(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)

        result = create_purchase_bill(
            user_id, vendor_id, "2026-08-01",
            [dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id)],
            first_payment_amount=100.0, first_payment_paid_at="2026-08-01",
        )
        assert bill_total_paid(result["purchase_bill_id"]) == 100.0


def test_create_purchase_bill_updates_max_discount_percent_when_given(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol", max_discount_percent=0)
        user_id = _make_admin(app)

        create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(max_discount_percent=15), medicine_id=medicine_id),
        ])
        assert get_medicine(medicine_id)["max_discount_percent"] == 15


# --- payments -------------------------------------------------------------

def test_record_payment_reduces_amount_due(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        record_payment(result["purchase_bill_id"], 100.0, "2026-08-02", user_id)
        assert bill_total_paid(result["purchase_bill_id"]) == 100.0
        balance = vendor_balance(vendor_id)
        assert balance["total_due"] == result["total_amount"] - 100.0


def test_record_payment_rejects_amount_exceeding_due(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        with pytest.raises(ValueError):
            record_payment(result["purchase_bill_id"], result["total_amount"] + 1, "2026-08-02", user_id)


def test_record_payment_rejects_non_positive_amount(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        with pytest.raises(ValueError):
            record_payment(result["purchase_bill_id"], 0, "2026-08-02", user_id)


def test_bill_total_paid_sums_multiple_payments(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=5, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        record_payment(result["purchase_bill_id"], 100.0, "2026-08-02", user_id)
        record_payment(result["purchase_bill_id"], 50.0, "2026-08-03", user_id)
        assert bill_total_paid(result["purchase_bill_id"]) == 150.0


def test_list_purchase_bills_reports_paid_and_due(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        record_payment(result["purchase_bill_id"], 100.0, "2026-08-02", user_id)
        bills = list_purchase_bills(vendor_id)
        assert len(bills) == 1
        assert bills[0]["total_paid"] == 100.0
        assert bills[0]["amount_due"] == result["total_amount"] - 100.0


def test_vendor_balance_rolls_up_across_bills(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        r1 = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        r2 = create_purchase_bill(user_id, vendor_id, "2026-08-05", [
            dict(_cetamol_item(quantity=1, cost_price_original=2.0), medicine_id=medicine_id),
        ])
        record_payment(r1["purchase_bill_id"], r1["total_amount"], "2026-08-02", user_id)
        balance = vendor_balance(vendor_id)
        assert balance["total_billed"] == r1["total_amount"] + r2["total_amount"]
        assert balance["total_paid"] == r1["total_amount"]
        assert balance["total_due"] == r2["total_amount"]


def test_get_purchase_bill_and_list_batches_and_payments(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        record_payment(result["purchase_bill_id"], 50.0, "2026-08-02", user_id, note="partial")

        bill = get_purchase_bill(result["purchase_bill_id"])
        assert bill["vendor_id"] == vendor_id
        assert len(list_batches_for_bill(result["purchase_bill_id"])) == 1
        payments = list_payments(result["purchase_bill_id"])
        assert len(payments) == 1
        assert payments[0]["amount"] == 50.0
        assert payments[0]["note"] == "partial"


# --- search_medicines_for_purchase ----------------------------------------

def test_search_medicines_for_purchase_includes_box_unit(app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
        results = search_medicines_for_purchase("ceta")
        assert len(results) == 1
        unit_names = {u["unit_name"] for u in results[0]["units"]}
        assert "Box" in unit_names


def _make_admin(app):
    from auth import create_user
    return create_user("admin1", "pw", "admin")


# --- routes -----------------------------------------------------------------

def test_new_purchase_bill_view_requires_admin(staff_client):
    resp = staff_client.get("/purchases/new")
    assert resp.status_code == 403


def test_new_purchase_bill_view_renders(admin_client, app):
    with app.app_context():
        add_vendor("ABC Vendors")
    resp = admin_client.get("/purchases/new")
    assert resp.status_code == 200
    assert b"ABC Vendors" in resp.data


def test_search_medicines_view_includes_box_unit(admin_client, app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
    resp = admin_client.get("/purchases/medicines/search?q=ceta")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert "Box" in {u["unit_name"] for u in data[0]["units"]}


def test_create_purchase_bill_view_multipart_creates_bill(admin_client, app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")

    items = [dict(_cetamol_item(quantity=2, cost_price_original=1.0), medicine_id=medicine_id)]
    resp = admin_client.post("/purchases", data={
        "vendor_id": str(vendor_id),
        "bill_date": "2026-08-01",
        "items_json": json.dumps(items),
        "bill_image": (io.BytesIO(b"fake image bytes"), "bill.jpg"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "purchase_bill_id" in data
    with app.app_context():
        assert len(list_batches(medicine_id)) == 1
        bill = get_purchase_bill(data["purchase_bill_id"])
        assert bill["bill_image_path"] is not None


def test_create_purchase_bill_view_invalid_returns_400(admin_client, app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol")
    items = [dict(_cetamol_item(quantity=2, cost_price_original=1.0), medicine_id=medicine_id)]
    resp = admin_client.post("/purchases", data={
        "vendor_id": "999",
        "bill_date": "2026-08-01",
        "items_json": json.dumps(items),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_purchase_bill_detail_view_renders(admin_client, app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        purchase_bill_id = result["purchase_bill_id"]
    resp = admin_client.get(f"/purchases/{purchase_bill_id}")
    assert resp.status_code == 200
    assert b"Cetamol" in resp.data


def test_purchase_bill_detail_view_404_for_unknown(admin_client):
    resp = admin_client.get("/purchases/999")
    assert resp.status_code == 404


def test_add_payment_view_records_payment_and_redirects(admin_client, app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        purchase_bill_id = result["purchase_bill_id"]
    resp = admin_client.post(f"/purchases/{purchase_bill_id}/payments", data={
        "amount": "100.0", "paid_at": "2026-08-02",
    })
    assert resp.status_code == 302
    with app.app_context():
        assert bill_total_paid(purchase_bill_id) == 100.0
