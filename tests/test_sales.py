import pytest

from inventory import get_medicine
from sales import create_sale, get_sale, list_sales, today_sales_total, void_sale
from helpers import make_box_file_medicine


def _setup_medicine(app, stock_boxes=5):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol", low_stock_threshold=50)
        from inventory import add_stock
        add_stock(medicine_id, "Box", stock_boxes)
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
        assert result["total"] == pytest.approx(4 * 2.5 + 1 * 45.0)
        medicine = get_medicine(medicine_id)
        assert medicine["stock_in_base_units"] == 5 * 240 - 4 - 20


def test_create_sale_rejects_insufficient_stock(app):
    medicine_id = _setup_medicine(app, stock_boxes=1)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "Box", "quantity": 5},
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
    assert any(u["unit_name"] == "Tablet" for u in data[0]["units"])


def test_finalize_sale_route_creates_sale_and_returns_redirect(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={"items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}]},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "sale_id" in data


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
        # Two line items for same medicine, together exceeding stock (1 box = 240 base units)
        # Each line item is 1 box = 240 base units, so 2 boxes = 480 exceeds 240 stock
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "Box", "quantity": 1},
                {"medicine_id": medicine_id, "unit_name": "Box", "quantity": 1},
            ])
        medicine = get_medicine(medicine_id)
        # Verify stock unchanged (no partial mutation)
        assert medicine["stock_in_base_units"] == 1 * 240


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
