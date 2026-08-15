import pytest

from inventory import get_medicine
from sales import create_sale, daily_sales_totals, get_sale, list_sales, today_sales_total, void_sale
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
        json={"items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}]},
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
        },
    )
    sale_id = response.get_json()["sale_id"]
    body = admin_client.get(f"/sales/{sale_id}/receipt").get_data(as_text=True)
    assert "Archana Giri" in body

    response2 = admin_client.post(
        "/sales",
        json={"items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}]},
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
