import pytest

from db import get_db
from inventory import get_medicine
from sales import (
    create_sale,
    create_sale_return,
    daily_sales_totals,
    get_sale,
    list_sale_returns,
    list_sales,
    returnable_sale_item_quantity,
    sales_register,
    today_sales_total,
    void_sale,
    void_sale_return,
)
from helpers import make_box_file_medicine, make_stock


def _setup_medicine(app, stock_boxes=5, max_discount_percent=0, name="Cetamol"):
    with app.app_context():
        medicine_id = make_box_file_medicine(name=name, low_stock_threshold=50,
                                              max_discount_percent=max_discount_percent)
        make_stock(medicine_id, "Box", stock_boxes,
                   cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        return medicine_id


def test_create_sale_decrements_stock_and_computes_total(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [
            {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4},
            {"medicine_id": medicine_id, "unit_name": "File", "quantity": 1},
        ])
        # Tablet = 1 base unit, File = 20 base units; MRP is 2.5/base unit.
        assert result["total"] == pytest.approx(4 * 2.5 + 1 * 20 * 2.5)
        medicine = get_medicine(medicine_id)
        assert medicine["stock_in_base_units"] == 5 * 240 - 4 - 20


def test_create_sale_rejects_insufficient_stock(app):
    medicine_id = _setup_medicine(app, stock_boxes=1)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        # 1 box = 240 base units = 12 files; requesting 100 files genuinely exceeds stock.
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "File", "quantity": 100},
            ])


def test_create_sale_rejects_box_unit_as_unsellable(app):
    medicine_id = _setup_medicine(app, stock_boxes=5)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        # Box is never sellable (is_sellable=0), so this must be rejected even though
        # stock is plentiful (5 boxes) — this exercises server-side enforcement of
        # is_sellable independent of the stock-sufficiency check.
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "Box", "quantity": 1},
            ])


def test_create_sale_rejects_unknown_unit(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "Pallet", "quantity": 1},
            ])


def test_void_sale_restores_stock(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [
            {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4},
        ])
        void_sale(result["sale_id"])
        medicine = get_medicine(medicine_id)
        assert medicine["stock_in_base_units"] == 5 * 240
        sale = get_sale(result["sale_id"])
        assert sale["sale"]["voided"] == 1


def test_void_sale_twice_raises(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [
            {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1},
        ])
        void_sale(result["sale_id"])
        with pytest.raises(ValueError):
            void_sale(result["sale_id"])


def test_today_sales_total_excludes_voided(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        r1 = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}])
        void_sale(r1["sale_id"])
        assert today_sales_total() == pytest.approx(2 * 2.5)


def test_sales_search_route_returns_matching_medicines(admin_client, app):
    _setup_medicine(app)
    response = admin_client.get("/sales/search?q=ceta")
    assert response.status_code == 200
    data = response.get_json()
    assert data[0]["name"] == "Cetamol"
    tablet_unit = next(u for u in data[0]["units"] if u["unit_name"] == "Tablet")
    assert tablet_unit["price"] == pytest.approx(2.5)
    assert "max_discount_percent" in data[0]


def test_finalize_sale_route_creates_sale_and_returns_redirect(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}],
            "tender_amount": 5,
        },
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "sale_id" in data


def test_finalize_sale_route_persists_patient_name(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}],
            "patient_name": "Archana Giri",
            "tender_amount": 5,
        },
    )
    data = response.get_json()
    with app.app_context():
        sale = get_sale(data["sale_id"])
        assert sale["sale"]["patient_name"] == "Archana Giri"


def test_finalize_sale_route_blank_patient_name_stored_as_none(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}],
            "patient_name": "   ",
            "tender_amount": 5,
        },
    )
    data = response.get_json()
    with app.app_context():
        sale = get_sale(data["sale_id"])
        assert sale["sale"]["patient_name"] is None


def test_receipt_shows_patient_name_or_walk_in(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}],
            "patient_name": "Archana Giri",
            "tender_amount": 5,
        },
    )
    sale_id = response.get_json()["sale_id"]
    body = admin_client.get(f"/sales/{sale_id}/receipt").get_data(as_text=True)
    assert "Archana Giri" in body

    response2 = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}],
            "tender_amount": 2.5,
        },
    )
    sale_id2 = response2.get_json()["sale_id"]
    body2 = admin_client.get(f"/sales/{sale_id2}/receipt").get_data(as_text=True)
    assert "Walk-in" in body2


def test_void_route_requires_admin(staff_client, app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("someone", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])
    response = staff_client.post(f"/sales/{result['sale_id']}/void")
    assert response.status_code == 403


def test_create_sale_rejects_duplicate_items_exceeding_stock(app):
    medicine_id = _setup_medicine(app, stock_boxes=1)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        # Two line items for the same medicine, together exceeding its stock (1 box = 240 base units).
        # Each line item is 7 files = 140 base units, so 2 lines = 280 exceeds 240 stock.
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "File", "quantity": 7},
                {"medicine_id": medicine_id, "unit_name": "File", "quantity": 7},
            ])
        medicine = get_medicine(medicine_id)
        # Verify stock unchanged (no partial mutation)
        assert medicine["stock_in_base_units"] == 1 * 240


def test_create_sale_item_mode_discount_capped_per_medicine(app):
    medicine_id = _setup_medicine(app, max_discount_percent=10)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [
            {"medicine_id": medicine_id, "unit_name": "Tablet",
             "quantity": 4, "discount_percent": 5},
        ], discount_mode="item")
        # unit_price is rounded to 2dp (the figure printed on the receipt line) before
        # being multiplied by quantity, so this is 4 * round(2.5 * 0.95, 2) = 4 * 2.38.
        assert result["total"] == pytest.approx(4 * 2.38)
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "Tablet",
                 "quantity": 4, "discount_percent": 15},
            ], discount_mode="item")


def test_create_sale_bill_mode_discount_capped_at_minimum_across_items(app):
    with app.app_context():
        low_cap_id = make_box_file_medicine(name="Cetamol", low_stock_threshold=50, max_discount_percent=5)
        make_stock(low_cap_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        high_cap_id = make_box_file_medicine(name="Napa", low_stock_threshold=50, max_discount_percent=20)
        make_stock(high_cap_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=3.0)
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        items = [
            {"medicine_id": low_cap_id, "unit_name": "Tablet", "quantity": 2},
            {"medicine_id": high_cap_id, "unit_name": "Tablet", "quantity": 2},
        ]
        with pytest.raises(ValueError):
            create_sale(user_id, items, discount_mode="bill", bill_discount_percent=10)
        result = create_sale(user_id, items, discount_mode="bill", bill_discount_percent=5)
        assert result["total"] == pytest.approx((2 * 2.0 + 2 * 3.0) * 0.95)


def test_create_sale_rejects_item_discount_when_mode_is_not_item(app):
    medicine_id = _setup_medicine(app, max_discount_percent=10)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "Tablet",
                 "quantity": 4, "discount_percent": 5},
            ], discount_mode="none")


def test_create_sale_rejects_bill_discount_when_mode_is_not_bill(app):
    medicine_id = _setup_medicine(app, max_discount_percent=10)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4},
            ], discount_mode="item", bill_discount_percent=5)


def test_create_sale_rejects_fractional_quantity(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2.5},
            ])
        medicine = get_medicine(medicine_id)
        # Verify stock unchanged (no partial mutation on rejected sale)
        assert medicine["stock_in_base_units"] == 5 * 240


def test_create_sale_rejects_bool_quantity(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": True},
            ])


def test_finalize_route_rejects_missing_items_key(admin_client, app):
    _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={"not_items": []},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_finalize_route_rejects_non_numeric_quantity(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={"items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": "not_a_number"}]},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_finalize_route_rejects_fractional_quantity(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={"items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2.5}]},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_list_sales_route_admin_sees_all_staff_sees_own(app, client):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        admin_id = create_user("boss", "bosspass", "admin")
        staff_id = create_user("clerk", "clerkpass", "staff")
        create_sale(admin_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])
        create_sale(staff_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}])

    admin_client = client
    admin_client.post("/login", data={"username": "boss", "password": "bosspass"})
    admin_resp = admin_client.get("/sales")
    assert admin_resp.status_code == 200
    admin_body = admin_resp.get_data(as_text=True)
    assert admin_body.count("/receipt") == 2
    admin_client.post("/logout")

    staff_client = client
    staff_client.post("/login", data={"username": "clerk", "password": "clerkpass"})
    staff_resp = staff_client.get("/sales")
    assert staff_resp.status_code == 200
    staff_body = staff_resp.get_data(as_text=True)
    assert staff_body.count("/receipt") == 1


def test_list_sales_business_logic_filters_by_user(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_a = create_user("alice", "pw", "staff")
        user_b = create_user("bob", "pw", "staff")
        create_sale(user_a, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])
        create_sale(user_b, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])

        all_sales = list_sales()
        assert len(all_sales) == 2

        a_sales = list_sales(user_id=user_a)
        assert len(a_sales) == 1
        assert a_sales[0]["user_id"] == user_a


def test_sales_search_excludes_box_unit(admin_client, app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
    response = admin_client.get("/sales/search?q=ceta")
    data = response.get_json()
    unit_names = {u["unit_name"] for u in data[0]["units"]}
    assert unit_names == {"File", "Tablet"}
    assert "photo_path" in data[0]
    assert "packaging_type" in data[0]


def test_get_sale_includes_seller_username(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("cashier1", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}])
        sale = get_sale(result["sale_id"])
        assert sale["sale"]["username"] == "cashier1"


def test_list_sales_includes_seller_username(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("cashier1", "pw", "staff")
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])
        sales = list_sales()
        assert sales[0]["username"] == "cashier1"


def test_profit_correctness_on_get_sale_and_list_sales(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol", low_stock_threshold=50, max_discount_percent=20)
        make_stock(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        from auth import create_user
        user_id = create_user("cashier1", "pw", "staff")
        result = create_sale(user_id, [
            {"medicine_id": medicine_id, "unit_name": "Tablet",
             "quantity": 4, "discount_percent": 10},
        ], discount_mode="item")
        # unit_price = 2.5 * 0.9 = 2.25; subtotal = 9.0; cost = 1.0 * 4 = 4.0; profit = 5.0
        sale = get_sale(result["sale_id"])
        assert sale["items"][0]["profit"] == pytest.approx(5.0)
        sales = list_sales()
        assert sales[0]["profit"] == pytest.approx(5.0)


def test_receipt_hides_cost_and_profit_from_staff_but_shows_admin(app, client):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        create_user("boss", "bosspass", "admin")
        owner_id = create_user("owner", "ownerpass", "staff")
        result = create_sale(owner_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}])
    sale_id = result["sale_id"]

    client.post("/login", data={"username": "owner", "password": "ownerpass"})
    staff_resp = client.get(f"/sales/{sale_id}/receipt")
    staff_body = staff_resp.get_data(as_text=True)
    assert "Profit" not in staff_body
    client.post("/logout")

    client.post("/login", data={"username": "boss", "password": "bosspass"})
    admin_resp = client.get(f"/sales/{sale_id}/receipt")
    admin_body = admin_resp.get_data(as_text=True)
    assert "Profit" in admin_body


def test_sales_list_hides_profit_from_staff_but_shows_admin(app, client):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        create_user("boss", "bosspass", "admin")
        owner_id = create_user("owner", "ownerpass", "staff")
        create_sale(owner_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}])

    client.post("/login", data={"username": "owner", "password": "ownerpass"})
    staff_resp = client.get("/sales")
    assert "Profit" not in staff_resp.get_data(as_text=True)
    client.post("/logout")

    client.post("/login", data={"username": "boss", "password": "bosspass"})
    admin_resp = client.get("/sales")
    assert "Profit" in admin_resp.get_data(as_text=True)


def test_receipt_route_forbids_other_staff_but_allows_owner_and_admin(app, client):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        create_user("boss", "bosspass", "admin")
        owner_id = create_user("owner", "ownerpass", "staff")
        create_user("intruder", "intruderpass", "staff")
        result = create_sale(owner_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])
    sale_id = result["sale_id"]

    # A different staff member must not be able to view someone else's receipt.
    client.post("/login", data={"username": "intruder", "password": "intruderpass"})
    other_resp = client.get(f"/sales/{sale_id}/receipt")
    assert other_resp.status_code == 403
    client.post("/logout")

    # The staff member who made the sale can still view their own receipt.
    client.post("/login", data={"username": "owner", "password": "ownerpass"})
    owner_resp = client.get(f"/sales/{sale_id}/receipt")
    assert owner_resp.status_code == 200
    client.post("/logout")

    # Admin can view any receipt regardless of who made the sale.
    client.post("/login", data={"username": "boss", "password": "bosspass"})
    admin_resp = client.get(f"/sales/{sale_id}/receipt")
    assert admin_resp.status_code == 200


def test_daily_sales_totals_aggregates_revenue_items_profit(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("cashier1", "pw", "staff")
        create_sale(user_id, [
            {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4},
        ])
        rows = daily_sales_totals(days=7)
        assert len(rows) == 1
        # MRP 2.5/base unit, cost 1.0/base unit, 4 tablets: revenue=10.0, items=4, profit=6.0
        assert rows[0]["revenue"] == pytest.approx(10.0)
        assert rows[0]["items_sold"] == 4
        assert rows[0]["profit"] == pytest.approx(6.0)


def test_daily_sales_totals_excludes_voided_sales(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("cashier1", "pw", "staff")
        result = create_sale(user_id, [
            {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4},
        ])
        void_sale(result["sale_id"])
        rows = daily_sales_totals(days=7)
        assert rows == []


def test_daily_sales_totals_only_returns_days_with_sales(app):
    with app.app_context():
        rows = daily_sales_totals(days=7)
        assert rows == []


def test_create_sale_computes_tender_and_change_for_cash(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        # 4 tablets @ 2.5 = 10.0 total.
        result = create_sale(
            user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}],
            payment_method="cash", tender_amount=15,
        )
        assert result["total"] == pytest.approx(10.0)
        assert result["change_amount"] == pytest.approx(5.0)
        sale = get_sale(result["sale_id"])
        assert sale["sale"]["payment_method"] == "cash"
        assert sale["sale"]["tender_amount"] == pytest.approx(15)
        assert sale["sale"]["change_amount"] == pytest.approx(5.0)


def test_create_sale_cash_omitted_tender_defaults_to_zero_change(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        # payment_method defaults to "cash" and tender_amount is omitted entirely, mirroring
        # the ~30 existing direct create_sale(...) call sites across the test suite.
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])
        assert result["change_amount"] == pytest.approx(0.0)
        sale = get_sale(result["sale_id"])
        assert sale["sale"]["payment_method"] == "cash"
        assert sale["sale"]["tender_amount"] is None
        assert sale["sale"]["change_amount"] == pytest.approx(0.0)


def test_create_sale_rejects_cash_tender_less_than_total(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        # 4 tablets @ 2.5 = 10.0 total; tendering 5 is genuinely insufficient.
        with pytest.raises(ValueError):
            create_sale(
                user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}],
                payment_method="cash", tender_amount=5,
            )


def test_create_sale_rejects_tender_amount_for_online_payment(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        with pytest.raises(ValueError):
            create_sale(
                user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}],
                payment_method="online", tender_amount=10,
            )


def test_create_sale_online_payment_has_no_tender_or_change(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(
            user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}],
            payment_method="online",
        )
        assert result["change_amount"] is None
        sale = get_sale(result["sale_id"])
        assert sale["sale"]["payment_method"] == "online"
        assert sale["sale"]["tender_amount"] is None
        assert sale["sale"]["change_amount"] is None


def test_create_sale_rejects_invalid_payment_method(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        with pytest.raises(ValueError):
            create_sale(
                user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}],
                payment_method="cheque",
            )


def test_finalize_route_requires_explicit_tender_for_cash_payment(admin_client, app):
    # This is the stricter route-level contract: create_sale is happy to default a missing
    # cash tender to "exact change", but the actual POS finalize route must not accept a
    # cash payment silently missing its tender_amount.
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}],
            "payment_method": "cash",
        },
    )
    assert response.status_code == 400
    assert "tender_amount" in response.get_json()["error"]


def test_finalize_route_accepts_cash_payment_with_explicit_tender(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}],
            "payment_method": "cash",
            "tender_amount": 10,
        },
    )
    assert response.status_code == 200
    data = response.get_json()
    # 2 tablets @ 2.5 = 5.0 total; tendered 10 => change 5.0.
    assert data["change_amount"] == pytest.approx(5.0)
    with app.app_context():
        sale = get_sale(data["sale_id"])
        assert sale["sale"]["tender_amount"] == pytest.approx(10)
        assert sale["sale"]["change_amount"] == pytest.approx(5.0)


def test_finalize_route_rejects_tender_amount_for_online_payment(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}],
            "payment_method": "online",
            "tender_amount": 10,
        },
    )
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_finalize_route_online_payment_without_tender_succeeds(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}],
            "payment_method": "online",
        },
    )
    assert response.status_code == 200


def test_finalize_route_persists_doctor_name(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}],
            "payment_method": "cash",
            "tender_amount": 10,
            "doctor_name": "Dr. Shrestha",
        },
    )
    data = response.get_json()
    with app.app_context():
        sale = get_sale(data["sale_id"])
        assert sale["sale"]["doctor_name"] == "Dr. Shrestha"


def test_receipt_shows_doctor_payment_method_and_tender_change_for_cash(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}],
            "payment_method": "cash",
            "tender_amount": 10,
            "doctor_name": "Dr. Shrestha",
        },
    )
    sale_id = response.get_json()["sale_id"]
    body = admin_client.get(f"/sales/{sale_id}/receipt").get_data(as_text=True)
    assert "Dr. Shrestha" in body
    assert "Cash" in body
    assert "Tender: Rs 10.00" in body
    assert "Change: Rs 5.00" in body


def test_receipt_hides_tender_and_change_for_online_payment(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}],
            "payment_method": "online",
        },
    )
    sale_id = response.get_json()["sale_id"]
    body = admin_client.get(f"/sales/{sale_id}/receipt").get_data(as_text=True)
    assert "Online" in body
    assert "Tender:" not in body
    assert "Not specified" in body


# --- sale returns -------------------------------------------------------------

def test_returnable_sale_item_quantity_starts_at_sale_quantity(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])
        sale_item_id = get_sale(result["sale_id"])["items"][0]["id"]
        assert returnable_sale_item_quantity(sale_item_id) == 4


def test_create_sale_return_increases_stock_and_never_mutates_sale_total(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])
        stock_before = get_medicine(medicine_id)["stock_in_base_units"]
        sale_total_before = get_sale(result["sale_id"])["sale"]["total"]

        ret = create_sale_return(
            result["sale_id"], [{"sale_item_id": get_sale(result["sale_id"])["items"][0]["id"], "quantity": 2}],
            "wrong_item", user_id,
        )
        # 2 tablets @ unit_price 2.5 (no discount) = 5.0
        assert ret["total_amount"] == pytest.approx(5.0)
        # Tablet = 1 base unit, so stock goes back up by 2.
        assert get_medicine(medicine_id)["stock_in_base_units"] == stock_before + 2
        # sales.total itself must never be mutated by a return -- the Sales
        # Register nets returns out via a joined subquery instead.
        assert get_sale(result["sale_id"])["sale"]["total"] == pytest.approx(sale_total_before)
        assert returnable_sale_item_quantity(get_sale(result["sale_id"])["items"][0]["id"]) == 2


def test_create_sale_return_rejects_more_than_returnable(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])
        sale_item_id = get_sale(result["sale_id"])["items"][0]["id"]
        with pytest.raises(ValueError):
            create_sale_return(
                result["sale_id"], [{"sale_item_id": sale_item_id, "quantity": 5}], "wrong_item", user_id,
            )


def test_create_sale_return_rejects_when_summed_rows_exceed_returnable(app):
    """Two return rows for the same sale_item_id must be validated against their
    combined total -- each row alone (3) is under the returnable amount (4), but
    their sum (6) is not."""
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])
        sale_item_id = get_sale(result["sale_id"])["items"][0]["id"]
        with pytest.raises(ValueError):
            create_sale_return(
                result["sale_id"],
                [
                    {"sale_item_id": sale_item_id, "quantity": 3},
                    {"sale_item_id": sale_item_id, "quantity": 3},
                ],
                "wrong_item", user_id,
            )
        # Nothing written -- validation fails before the write pass begins.
        assert get_medicine(medicine_id)["stock_in_base_units"] == 5 * 240 - 4


def test_create_sale_return_rejects_cross_sale_item(app):
    """A sale_item_id belonging to a different sale than the one named in the
    call must be rejected -- returns are scoped to a specific sale's own items."""
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        sale_a = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}])
        sale_b = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}])
        item_from_a = get_sale(sale_a["sale_id"])["items"][0]["id"]
        with pytest.raises(ValueError):
            create_sale_return(sale_b["sale_id"], [{"sale_item_id": item_from_a, "quantity": 1}], "wrong_item", user_id)


def test_create_sale_return_rejects_invalid_reason(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}])
        sale_item_id = get_sale(result["sale_id"])["items"][0]["id"]
        with pytest.raises(ValueError):
            create_sale_return(result["sale_id"], [{"sale_item_id": sale_item_id, "quantity": 1}], "bogus", user_id)


def test_create_sale_return_rejects_on_voided_sale(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}])
        sale_item_id = get_sale(result["sale_id"])["items"][0]["id"]
        void_sale(result["sale_id"])
        with pytest.raises(ValueError):
            create_sale_return(result["sale_id"], [{"sale_item_id": sale_item_id, "quantity": 1}], "wrong_item", user_id)


def test_void_sale_return_reduces_stock_back_and_marks_voided(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])
        stock_before_return = get_medicine(medicine_id)["stock_in_base_units"]
        sale_item_id = get_sale(result["sale_id"])["items"][0]["id"]

        ret = create_sale_return(result["sale_id"], [{"sale_item_id": sale_item_id, "quantity": 2}], "wrong_item", user_id)
        assert get_medicine(medicine_id)["stock_in_base_units"] == stock_before_return + 2

        void_sale_return(ret["sale_return_id"])
        assert get_medicine(medicine_id)["stock_in_base_units"] == stock_before_return
        assert returnable_sale_item_quantity(sale_item_id) == 4

        with pytest.raises(ValueError):
            void_sale_return(ret["sale_return_id"])


def test_void_sale_return_rejects_when_restocked_units_have_since_been_resold(app):
    """The restocked units from a return can be resold (or adjusted away) before
    the return itself is voided -- voiding must not drive stock negative in
    that case, unlike a purchase-return void which only ever adds stock back."""
    medicine_id = _setup_medicine(app, stock_boxes=1)  # 240 base units
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        sale1 = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 200}])
        # stock: 240 - 200 = 40
        sale_item_id = get_sale(sale1["sale_id"])["items"][0]["id"]
        ret = create_sale_return(sale1["sale_id"], [{"sale_item_id": sale_item_id, "quantity": 100}], "wrong_item", user_id)
        # stock: 40 + 100 = 140
        assert get_medicine(medicine_id)["stock_in_base_units"] == 140

        # Those restocked 100 tablets get resold before the return is voided.
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 100}])
        # stock: 140 - 100 = 40 -- less than the 100 this return would need to remove.
        assert get_medicine(medicine_id)["stock_in_base_units"] == 40

        with pytest.raises(ValueError):
            void_sale_return(ret["sale_return_id"])
        # Nothing changed -- the guard must reject before mutating anything.
        assert get_medicine(medicine_id)["stock_in_base_units"] == 40


def test_void_sale_rejects_when_active_return_exists(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])
        sale_item_id = get_sale(result["sale_id"])["items"][0]["id"]
        ret = create_sale_return(result["sale_id"], [{"sale_item_id": sale_item_id, "quantity": 1}], "wrong_item", user_id)

        with pytest.raises(ValueError):
            void_sale(result["sale_id"])

        # Once the only active return is voided, voiding the sale is allowed again.
        void_sale_return(ret["sale_return_id"])
        void_sale(result["sale_id"])
        assert get_sale(result["sale_id"])["sale"]["voided"] == 1


def test_list_sale_returns_includes_items(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])
        sale_item_id = get_sale(result["sale_id"])["items"][0]["id"]
        create_sale_return(result["sale_id"], [{"sale_item_id": sale_item_id, "quantity": 1}], "wrong_item", user_id)

        returns = list_sale_returns(result["sale_id"])
        assert len(returns) == 1
        assert returns[0]["items"][0]["medicine_name"] == "Cetamol"


def test_sale_returns_lookup_route_rejects_staff(staff_client):
    assert staff_client.get("/sales/returns").status_code == 403


def test_sale_returns_lookup_route_allows_admin(admin_client):
    assert admin_client.get("/sales/returns").status_code == 200


def test_sale_returns_search_route_matches_by_patient_name(admin_client, app):
    medicine_id = _setup_medicine(app)
    admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}],
            "patient_name": "Archana Giri", "tender_amount": 5,
        },
    )
    resp = admin_client.get("/sales/returns/search?q=archana")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["patient_name"] == "Archana Giri"


def test_sale_returns_search_route_empty_query_returns_empty(admin_client, app):
    medicine_id = _setup_medicine(app)
    admin_client.post(
        "/sales",
        json={"items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}], "tender_amount": 5},
    )
    resp = admin_client.get("/sales/returns/search?q=")
    assert resp.get_json() == []


def test_sale_returns_search_route_excludes_voided_sales(admin_client, app):
    medicine_id = _setup_medicine(app)
    resp = admin_client.post(
        "/sales",
        json={
            "items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}],
            "patient_name": "Archana Giri", "tender_amount": 5,
        },
    )
    sale_id = resp.get_json()["sale_id"]
    admin_client.post(f"/sales/{sale_id}/void")
    assert admin_client.get("/sales/returns/search?q=archana").get_json() == []


def test_sale_item_returnable_route(admin_client, app):
    medicine_id = _setup_medicine(app)
    resp = admin_client.post(
        "/sales",
        json={"items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}], "tender_amount": 10},
    )
    sale_id = resp.get_json()["sale_id"]
    with app.app_context():
        sale_item_id = get_sale(sale_id)["items"][0]["id"]
    r = admin_client.get(f"/sales/{sale_id}/items/{sale_item_id}/returnable")
    assert r.status_code == 200
    assert r.get_json()["returnable"] == 4


def test_sale_item_returnable_route_requires_admin(staff_client, app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("owner", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])
        sale_item_id = get_sale(result["sale_id"])["items"][0]["id"]
    resp = staff_client.get(f"/sales/{result['sale_id']}/items/{sale_item_id}/returnable")
    assert resp.status_code == 403


def test_create_sale_return_route_creates_return(admin_client, app):
    medicine_id = _setup_medicine(app)
    resp = admin_client.post(
        "/sales",
        json={"items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}], "tender_amount": 10},
    )
    sale_id = resp.get_json()["sale_id"]
    with app.app_context():
        sale_item_id = get_sale(sale_id)["items"][0]["id"]
    r = admin_client.post(
        f"/sales/{sale_id}/returns",
        json={"items": [{"sale_item_id": sale_item_id, "quantity": 1}], "reason": "wrong_item"},
    )
    assert r.status_code == 200
    assert "sale_return_id" in r.get_json()


def test_create_sale_return_route_requires_admin(staff_client, app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("owner", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])
        sale_item_id = get_sale(result["sale_id"])["items"][0]["id"]
    resp = staff_client.post(
        f"/sales/{result['sale_id']}/returns",
        json={"items": [{"sale_item_id": sale_item_id, "quantity": 1}], "reason": "wrong_item"},
    )
    assert resp.status_code == 403


def test_void_sale_return_route_redirects(admin_client, app):
    medicine_id = _setup_medicine(app)
    resp = admin_client.post(
        "/sales",
        json={"items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}], "tender_amount": 10},
    )
    sale_id = resp.get_json()["sale_id"]
    with app.app_context():
        sale_item_id = get_sale(sale_id)["items"][0]["id"]
        user_id = get_sale(sale_id)["sale"]["user_id"]
        ret = create_sale_return(sale_id, [{"sale_item_id": sale_item_id, "quantity": 1}], "wrong_item", user_id)
    r = admin_client.post(f"/sales/returns/{ret['sale_return_id']}/void")
    assert r.status_code == 302


def test_void_sale_return_route_requires_admin(staff_client, app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("owner", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])
        sale_item_id = get_sale(result["sale_id"])["items"][0]["id"]
        ret = create_sale_return(result["sale_id"], [{"sale_item_id": sale_item_id, "quantity": 1}], "wrong_item", user_id)
    resp = staff_client.post(f"/sales/returns/{ret['sale_return_id']}/void")
    assert resp.status_code == 403


# --- sales register -------------------------------------------------------------

def _set_sale_timestamp(sale_id, timestamp):
    db = get_db()
    db.execute("UPDATE sales SET timestamp = ? WHERE id = ?", (timestamp, sale_id))
    db.commit()


def test_sales_register_date_filtering(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        old_sale = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])
        new_sale = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])
        _set_sale_timestamp(old_sale["sale_id"], "2026-01-01 10:00:00")
        _set_sale_timestamp(new_sale["sale_id"], "2026-06-15 10:00:00")

        rows = sales_register(date_from="2026-05-01", date_to="2026-12-31")
        ids = {r["id"] for r in rows}
        assert new_sale["sale_id"] in ids
        assert old_sale["sale_id"] not in ids


def test_sales_register_nets_out_return_amount_without_mutating_sale_total(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])
        sale_id = result["sale_id"]
        sale_item_id = get_sale(sale_id)["items"][0]["id"]
        create_sale_return(sale_id, [{"sale_item_id": sale_item_id, "quantity": 2}], "wrong_item", user_id)

        rows = sales_register()
        row = next(r for r in rows if r["id"] == sale_id)
        # 4 tablets @ 2.5 = 10.0 total; 2 returned @ 2.5 = 5.0 returned; net = 5.0.
        assert row["total"] == pytest.approx(10.0)
        assert row["returned_amount"] == pytest.approx(5.0)
        assert row["net_total"] == pytest.approx(5.0)
        # The underlying sales.total column itself is never mutated by a return.
        assert get_sale(sale_id)["sale"]["total"] == pytest.approx(10.0)


def test_sales_register_search_matches_patient_doctor_or_username(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        alice = create_user("alice", "pw", "staff")
        bob = create_user("bob", "pw", "staff")
        create_sale(alice, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}],
                    patient_name="Archana Giri", doctor_name="Dr. Shrestha")
        create_sale(bob, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}],
                    patient_name="Someone Else")

        by_patient = sales_register(search="archana")
        assert len(by_patient) == 1
        assert by_patient[0]["username"] == "alice"

        by_doctor = sales_register(search="shrestha")
        assert len(by_doctor) == 1

        by_username = sales_register(search="bob")
        assert len(by_username) == 1
        assert by_username[0]["patient_name"] == "Someone Else"


def test_sales_register_route_rejects_staff(staff_client):
    assert staff_client.get("/sales/register").status_code == 403


def test_sales_register_route_allows_admin(admin_client):
    assert admin_client.get("/sales/register").status_code == 200
