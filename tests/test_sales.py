import pytest

from inventory import add_medicine, get_medicine
from sales import create_sale, get_sale, today_sales_total, void_sale

TABLET_UNITS = [
    {"unit_name": "Box", "qty_in_base_units": 240, "price": 480.0},
    {"unit_name": "File", "qty_in_base_units": 20, "price": 45.0},
    {"unit_name": "Tablet", "qty_in_base_units": 1, "price": 2.5},
]


def _setup_medicine(app, stock_boxes=5):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
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
