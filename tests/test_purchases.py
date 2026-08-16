import io
import json

import pytest

from inventory import get_medicine, list_stock_receipts
from purchases import (
    bill_total_paid,
    convert_to_npr,
    create_purchase_bill,
    create_purchase_return,
    get_purchase_bill,
    list_payments,
    list_purchase_bills,
    list_purchase_returns,
    list_stock_receipts_for_bill,
    record_payment,
    returnable_quantity,
    search_medicines_for_purchase,
    vendor_balance,
    void_purchase_return,
)
from vendors import add_vendor
from companies import add_company
from helpers import make_box_file_medicine, make_stock


def _cetamol_item(quantity=2, unit_name="Box",
                   cost_price_original=1.0, cost_currency="NPR",
                   mrp_original=2.0, mrp_currency="NPR",
                   max_discount_percent=None, batch_number=None, expiry_date=None):
    return {
        "unit_name": unit_name, "quantity": quantity,
        "cost_price_original": cost_price_original, "cost_currency": cost_currency,
        "mrp_original": mrp_original, "mrp_currency": mrp_currency,
        "max_discount_percent": max_discount_percent,
        "batch_number": batch_number, "expiry_date": expiry_date,
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

def test_create_purchase_bill_creates_one_stock_receipt_per_item(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        cetamol_id = make_box_file_medicine(name="Cetamol")
        pantop_id = make_box_file_medicine(name="Pantop")
        user_id = _make_admin(app)

        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(), medicine_id=cetamol_id),
            dict(_cetamol_item(quantity=1), medicine_id=pantop_id),
        ])

        assert len(list_stock_receipts(cetamol_id)) == 1
        assert len(list_stock_receipts(pantop_id)) == 1
        receipt = list_stock_receipts(cetamol_id)[0]
        assert receipt["purchase_bill_id"] == result["purchase_bill_id"]
        assert receipt["base_units_received"] == 2 * 240


def test_create_purchase_bill_converts_inr_cost_and_keeps_original(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)

        create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(cost_price_original=10.0, cost_currency="INR"), medicine_id=medicine_id),
        ])

        receipt = list_stock_receipts(medicine_id)[0]
        assert receipt["cost_currency"] == "INR"
        assert receipt["cost_price_original"] == 10.0
        assert receipt["cost_price_per_base_unit"] == 16.0  # 10 INR * 1.60


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

        assert list_stock_receipts(medicine_id) == []
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


def test_create_purchase_bill_stores_batch_and_expiry(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)

        create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(batch_number="B100", expiry_date="2027-01-01"), medicine_id=medicine_id),
        ])

        receipt = list_stock_receipts(medicine_id)[0]
        assert receipt["batch_number"] == "B100"
        assert receipt["expiry_date"] == "2027-01-01"


def test_create_purchase_bill_batch_and_expiry_are_optional(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)

        create_purchase_bill(user_id, vendor_id, "2026-08-01", [dict(_cetamol_item(), medicine_id=medicine_id)])

        receipt = list_stock_receipts(medicine_id)[0]
        assert receipt["batch_number"] is None
        assert receipt["expiry_date"] is None


def test_create_purchase_bill_converts_inr_mrp_and_keeps_original(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)

        create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(mrp_original=10.0, mrp_currency="INR"), medicine_id=medicine_id),
        ])

        receipt = list_stock_receipts(medicine_id)[0]
        assert receipt["mrp_currency"] == "INR"
        assert receipt["mrp_original"] == 10.0
        assert receipt["mrp_per_base_unit"] == 16.0  # 10 INR * 1.60


def test_create_purchase_bill_rejects_invalid_expiry_date_format(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        with pytest.raises(ValueError):
            create_purchase_bill(user_id, vendor_id, "2026-08-01", [
                dict(_cetamol_item(expiry_date="not-a-date"), medicine_id=medicine_id),
            ])


def test_create_purchase_bill_rejects_invalid_expiry_atomically(app):
    """A bad expiry on the 2nd item must not leave the 1st item's receipt committed."""
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        with pytest.raises(ValueError):
            create_purchase_bill(user_id, vendor_id, "2026-08-01", [
                dict(_cetamol_item(), medicine_id=medicine_id),
                dict(_cetamol_item(expiry_date="30-02-2027"), medicine_id=medicine_id),
            ])
        assert list_stock_receipts(medicine_id) == []
        assert get_medicine(medicine_id)["stock_in_base_units"] == 0


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


def test_list_purchase_bills_filters_by_date_range_across_vendors(app):
    with app.app_context():
        vendor1 = add_vendor("ABC Vendors")
        vendor2 = add_vendor("XYZ Traders")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        create_purchase_bill(user_id, vendor1, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        create_purchase_bill(user_id, vendor2, "2026-08-10", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        create_purchase_bill(user_id, vendor1, "2026-08-15", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])

        assert len(list_purchase_bills()) == 3

        ranged = list_purchase_bills(date_from="2026-08-05", date_to="2026-08-12")
        assert len(ranged) == 1
        assert ranged[0]["vendor_id"] == vendor2

        scoped = list_purchase_bills(vendor_id=vendor1, date_from="2026-08-05")
        assert len(scoped) == 1
        assert scoped[0]["bill_date"] == "2026-08-15"


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


def test_get_purchase_bill_and_list_stock_receipts_and_payments(app):
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
        assert len(list_stock_receipts_for_bill(result["purchase_bill_id"])) == 1
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


def test_search_medicines_for_purchase_includes_company_cost_and_mrp(app):
    with app.app_context():
        company_id = add_company("Cipla")
        from inventory import add_medicine
        medicine_id = add_medicine("Cetamol", "box_file", 10, tablets_per_file=20,
                                    files_per_box=12, company_id=company_id)
        make_stock(medicine_id, cost_price_per_base_unit=1.5, mrp_per_base_unit=3.0)

        results = search_medicines_for_purchase("ceta")

        assert len(results) == 1
        assert results[0]["company_name"] == "Cipla"
        assert results[0]["cost_price_per_base_unit"] == 1.5
        assert results[0]["mrp_per_base_unit"] == 3.0


def test_search_medicines_for_purchase_company_name_none_when_unlinked(app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
        results = search_medicines_for_purchase("ceta")
        assert results[0]["company_name"] is None


# --- purchase returns -------------------------------------------------------

def test_returnable_quantity_starts_at_received_quantity(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=5, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        assert returnable_quantity(result["purchase_bill_id"], medicine_id, "Box") == 5


def test_create_purchase_return_reduces_stock_and_bill_total(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=5, cost_price_original=1.0, mrp_original=2.0),
                 medicine_id=medicine_id),
        ])
        stock_before = get_medicine(medicine_id)["stock_in_base_units"]

        ret = create_purchase_return(
            result["purchase_bill_id"], [{"medicine_id": medicine_id, "unit_name": "Box", "quantity": 2}],
            "damaged", user_id,
        )
        # 2 boxes = 480 base units at 1.0 NPR/base unit = 480.0
        assert ret["total_amount"] == 480.0
        assert get_medicine(medicine_id)["stock_in_base_units"] == stock_before - 2 * 240
        bill = get_purchase_bill(result["purchase_bill_id"])
        assert bill["total_amount"] == result["total_amount"] - 480.0


def test_create_purchase_return_rejects_more_than_returnable(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=2, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        with pytest.raises(ValueError):
            create_purchase_return(
                result["purchase_bill_id"],
                [{"medicine_id": medicine_id, "unit_name": "Box", "quantity": 3}],
                "damaged", user_id,
            )


def test_create_purchase_return_rejects_more_than_current_stock(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=2, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        # Box is never sellable, so simulate the received stock having left the shop
        # (e.g. broken down and sold as loose tablets) via a stock adjustment, exercising
        # the "can't return stock that's no longer on hand" guard.
        from inventory import record_stock_adjustment
        record_stock_adjustment(medicine_id, "Box", 2, "decrease", "damaged", user_id)

        with pytest.raises(ValueError):
            create_purchase_return(
                result["purchase_bill_id"],
                [{"medicine_id": medicine_id, "unit_name": "Box", "quantity": 1}],
                "damaged", user_id,
            )


def test_void_purchase_return_restores_stock_and_bill_total(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=5, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        stock_before = get_medicine(medicine_id)["stock_in_base_units"]
        bill_total_before = get_purchase_bill(result["purchase_bill_id"])["total_amount"]

        ret = create_purchase_return(
            result["purchase_bill_id"], [{"medicine_id": medicine_id, "unit_name": "Box", "quantity": 2}],
            "damaged", user_id,
        )
        void_purchase_return(ret["purchase_return_id"])

        assert get_medicine(medicine_id)["stock_in_base_units"] == stock_before
        assert get_purchase_bill(result["purchase_bill_id"])["total_amount"] == bill_total_before
        with pytest.raises(ValueError):
            void_purchase_return(ret["purchase_return_id"])


def test_list_purchase_returns_includes_items(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=5, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        create_purchase_return(
            result["purchase_bill_id"], [{"medicine_id": medicine_id, "unit_name": "Box", "quantity": 1}],
            "damaged", user_id,
        )
        returns = list_purchase_returns(result["purchase_bill_id"])
        assert len(returns) == 1
        assert returns[0]["items"][0]["medicine_name"] == "Cetamol"


def test_returnable_quantity_scoped_by_batch_when_bill_has_multiple_batches(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=3, cost_price_original=1.0, batch_number="B1"), medicine_id=medicine_id),
            dict(_cetamol_item(quantity=4, cost_price_original=1.5, batch_number="B2"), medicine_id=medicine_id),
        ])
        purchase_bill_id = result["purchase_bill_id"]

        # Omitting batch_number aggregates across every batch on the bill (backward compatible).
        assert returnable_quantity(purchase_bill_id, medicine_id, "Box") == 7
        # Scoping by batch_number, each batch's returnable is independent of the other.
        assert returnable_quantity(purchase_bill_id, medicine_id, "Box", batch_number="B1") == 3
        assert returnable_quantity(purchase_bill_id, medicine_id, "Box", batch_number="B2") == 4


def test_create_purchase_return_scoped_by_batch_uses_that_batchs_cost(app):
    """Two batches of the same medicine/unit on one bill, at different costs --
    a batch-scoped return must net out against its own batch's cost and reduce
    only that batch's returnable, leaving the other batch untouched."""
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=3, cost_price_original=1.0, batch_number="B1"), medicine_id=medicine_id),
            dict(_cetamol_item(quantity=4, cost_price_original=2.0, batch_number="B2"), medicine_id=medicine_id),
        ])
        purchase_bill_id = result["purchase_bill_id"]

        ret = create_purchase_return(
            purchase_bill_id,
            [{"medicine_id": medicine_id, "unit_name": "Box", "quantity": 2, "batch_number": "B2"}],
            "damaged", user_id,
        )
        # 2 boxes from batch B2 = 480 base units at 2.0 NPR/base unit = 960.0 (not B1's 1.0 cost)
        assert ret["total_amount"] == 960.0
        assert returnable_quantity(purchase_bill_id, medicine_id, "Box", batch_number="B1") == 3
        assert returnable_quantity(purchase_bill_id, medicine_id, "Box", batch_number="B2") == 2


def test_create_purchase_return_handles_multiple_batches_in_one_call(app):
    """One return submission covering both batches of a two-batch bill --
    each item nets out against its own batch's cost and returnable."""
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=3, cost_price_original=1.0, batch_number="B1"), medicine_id=medicine_id),
            dict(_cetamol_item(quantity=4, cost_price_original=2.0, batch_number="B2"), medicine_id=medicine_id),
        ])
        purchase_bill_id = result["purchase_bill_id"]

        ret = create_purchase_return(
            purchase_bill_id,
            [
                {"medicine_id": medicine_id, "unit_name": "Box", "quantity": 1, "batch_number": "B1"},
                {"medicine_id": medicine_id, "unit_name": "Box", "quantity": 2, "batch_number": "B2"},
            ],
            "damaged", user_id,
        )
        # B1: 1 box * 240 base units * 1.0 = 240.0 ; B2: 2 boxes * 240 base units * 2.0 = 960.0
        assert ret["total_amount"] == 1200.0
        assert returnable_quantity(purchase_bill_id, medicine_id, "Box", batch_number="B1") == 2
        assert returnable_quantity(purchase_bill_id, medicine_id, "Box", batch_number="B2") == 2


def test_create_purchase_return_rejects_when_summed_rows_exceed_returnable(app):
    """Two return rows for the same (medicine, unit, batch) key must be validated
    against their combined total, not just individually -- each row alone (3) is
    under the returnable amount (5), but their sum (6) is not."""
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=5, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        purchase_bill_id = result["purchase_bill_id"]

        with pytest.raises(ValueError):
            create_purchase_return(
                purchase_bill_id,
                [
                    {"medicine_id": medicine_id, "unit_name": "Box", "quantity": 3},
                    {"medicine_id": medicine_id, "unit_name": "Box", "quantity": 3},
                ],
                "damaged", user_id,
            )
        # Nothing written -- validation fails before the write pass begins.
        assert get_medicine(medicine_id)["stock_in_base_units"] == 5 * 240
        assert get_purchase_bill(purchase_bill_id)["total_amount"] == result["total_amount"]


def test_create_purchase_return_scoped_request_sees_prior_unscoped_return(app):
    """Regression test: a bill has a single batch/receipt of 10 boxes. An
    unscoped return (no batch_number) is submitted for 6 of them, leaving 4
    returnable. A later return that names that exact batch must see the
    unscoped return as already counted against it -- an unscoped return
    doesn't record which batch it came from, so it has to be conservatively
    assumed to have come from every batch on the bill. Before the fix, the
    batch-scoped branch of returnable_quantity only looked at other returns
    that also named that same batch, so this second request (8, more than
    the 4 actually remaining) would incorrectly be accepted and double-count
    stock/bill-total reductions for goods only received once."""
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=10, cost_price_original=1.0, batch_number="B1"),
                 medicine_id=medicine_id),
        ])
        purchase_bill_id = result["purchase_bill_id"]

        # Unscoped return for 6 of the 10 boxes.
        create_purchase_return(
            purchase_bill_id,
            [{"medicine_id": medicine_id, "unit_name": "Box", "quantity": 6}],
            "damaged", user_id,
        )
        assert returnable_quantity(purchase_bill_id, medicine_id, "Box", batch_number="B1") == 4

        stock_before = get_medicine(medicine_id)["stock_in_base_units"]
        bill_total_before = get_purchase_bill(purchase_bill_id)["total_amount"]

        # Only 4 remain against batch B1 -- requesting 8 more (naming the batch)
        # must be rejected, not silently accepted as it would be pre-fix.
        with pytest.raises(ValueError):
            create_purchase_return(
                purchase_bill_id,
                [{"medicine_id": medicine_id, "unit_name": "Box", "quantity": 8, "batch_number": "B1"}],
                "damaged", user_id,
            )
        # Nothing further written -- stock and bill total unchanged by the rejected request.
        assert get_medicine(medicine_id)["stock_in_base_units"] == stock_before
        assert get_purchase_bill(purchase_bill_id)["total_amount"] == bill_total_before


def test_create_purchase_return_rejects_combined_scoped_and_unscoped_rows_in_one_call(app):
    """An unscoped row and a batch-scoped row for the same medicine/unit,
    submitted together in one return call, must be validated against their
    combined total -- they compete for the same underlying receipt pool, not
    two independent ones."""
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=10, cost_price_original=1.0, batch_number="B1"),
                 medicine_id=medicine_id),
        ])
        purchase_bill_id = result["purchase_bill_id"]

        with pytest.raises(ValueError):
            create_purchase_return(
                purchase_bill_id,
                [
                    {"medicine_id": medicine_id, "unit_name": "Box", "quantity": 6},
                    {"medicine_id": medicine_id, "unit_name": "Box", "quantity": 8, "batch_number": "B1"},
                ],
                "damaged", user_id,
            )
        # Nothing written -- validation fails before the write pass begins.
        assert get_medicine(medicine_id)["stock_in_base_units"] == 10 * 240
        assert get_purchase_bill(purchase_bill_id)["total_amount"] == result["total_amount"]


def test_create_purchase_return_route_creates_return(admin_client, app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=5, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        purchase_bill_id = result["purchase_bill_id"]
    resp = admin_client.post(
        f"/purchases/{purchase_bill_id}/returns",
        json={"items": [{"medicine_id": medicine_id, "unit_name": "Box", "quantity": 1}], "reason": "damaged"},
    )
    assert resp.status_code == 200
    assert "purchase_return_id" in resp.get_json()


def test_void_purchase_return_route_redirects(admin_client, app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=5, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        purchase_bill_id = result["purchase_bill_id"]
        ret = create_purchase_return(
            purchase_bill_id, [{"medicine_id": medicine_id, "unit_name": "Box", "quantity": 1}],
            "damaged", user_id,
        )
    resp = admin_client.post(f"/purchases/returns/{ret['purchase_return_id']}/void")
    assert resp.status_code == 302


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
    # Vendor picker is AJAX-based now (GET /vendors/search) -- no preloaded <option> list.
    assert b"vendor-search-input" in resp.data
    assert b"ABC Vendors" not in resp.data


def test_new_purchase_bill_view_preselects_vendor_from_query_param(admin_client, app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
    resp = admin_client.get(f"/purchases/new?vendor_id={vendor_id}")
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
        assert len(list_stock_receipts(medicine_id)) == 1
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


# --- Purchase Book -----------------------------------------------------------

def test_purchase_book_view_requires_admin(staff_client):
    resp = staff_client.get("/purchases")
    assert resp.status_code == 403


def test_purchase_book_view_renders_bills_across_vendors(admin_client, app):
    with app.app_context():
        vendor1 = add_vendor("ABC Vendors")
        vendor2 = add_vendor("XYZ Traders")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        create_purchase_bill(user_id, vendor1, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        create_purchase_bill(user_id, vendor2, "2026-08-05", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
    resp = admin_client.get("/purchases")
    assert resp.status_code == 200
    assert b"ABC Vendors" in resp.data
    assert b"XYZ Traders" in resp.data


def test_purchase_book_view_filters_by_date_range(admin_client, app):
    with app.app_context():
        vendor1 = add_vendor("ABC Vendors")
        vendor2 = add_vendor("XYZ Traders")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        create_purchase_bill(user_id, vendor1, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        create_purchase_bill(user_id, vendor2, "2026-08-10", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
    resp = admin_client.get("/purchases?date_from=2026-08-05&date_to=2026-08-15")
    assert resp.status_code == 200
    # The supplier filter <select> always lists every vendor as an <option>, so a
    # filtered-out vendor still appears once there -- but only the matching
    # vendor's name appears a second time, inside its bill's table row.
    assert resp.data.count(b"XYZ Traders") == 2
    assert resp.data.count(b"ABC Vendors") == 1


def test_purchase_book_view_filters_by_vendor(admin_client, app):
    with app.app_context():
        vendor1 = add_vendor("ABC Vendors")
        vendor2 = add_vendor("XYZ Traders")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        create_purchase_bill(user_id, vendor1, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
        create_purchase_bill(user_id, vendor2, "2026-08-05", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0), medicine_id=medicine_id),
        ])
    resp = admin_client.get(f"/purchases?vendor_id={vendor1}")
    assert resp.status_code == 200
    # Same reasoning as the date-range test: the supplier <select> lists every
    # vendor once regardless of the filter; only the matching vendor's name
    # appears a second time, inside its bill's table row.
    assert resp.data.count(b"ABC Vendors") == 2
    assert resp.data.count(b"XYZ Traders") == 1


# --- Purchase Report -----------------------------------------------------------

def test_purchase_report_view_requires_admin(staff_client):
    resp = staff_client.get("/purchases/1/report")
    assert resp.status_code == 403


def test_purchase_report_view_renders(admin_client, app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        medicine_id = make_box_file_medicine(name="Cetamol")
        user_id = _make_admin(app)
        result = create_purchase_bill(user_id, vendor_id, "2026-08-01", [
            dict(_cetamol_item(quantity=1, cost_price_original=1.0, batch_number="B1",
                                expiry_date="2027-01-01"), medicine_id=medicine_id),
        ])
        purchase_bill_id = result["purchase_bill_id"]
    resp = admin_client.get(f"/purchases/{purchase_bill_id}/report")
    assert resp.status_code == 200
    assert b"Cetamol" in resp.data
    assert b"B1" in resp.data
    assert b"2027-01-01" in resp.data
    assert b"ABC Vendors" in resp.data


def test_purchase_report_view_404_for_unknown(admin_client):
    resp = admin_client.get("/purchases/999/report")
    assert resp.status_code == 404
