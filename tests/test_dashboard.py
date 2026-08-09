from auth import create_user
from sales import create_sale
from helpers import make_batch, make_box_file_medicine


def test_dashboard_shows_low_stock(admin_client, app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol", low_stock_threshold=100)
        make_batch(medicine_id, "Tablet", 10, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)  # below threshold of 100

    response = admin_client.get("/")
    assert response.status_code == 200
    assert b"Cetamol" in response.data


def test_dashboard_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_dashboard_shows_todays_sales_total(admin_client, app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Napa", low_stock_threshold=100)
        batch_id = make_batch(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        user_id = create_user("cashier1", "pw", "staff")
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "batch_id": batch_id, "quantity": 4}])

    response = admin_client.get("/")
    assert response.status_code == 200
    assert b"10.00" in response.data  # 4 tablets * 2.5 price = 10.00


def test_dashboard_shows_total_products(admin_client, app):
    with app.app_context():
        from helpers import make_box_file_medicine
        make_box_file_medicine(name="Cetamol")
        make_box_file_medicine(name="Napa")

    response = admin_client.get("/")
    assert response.status_code == 200
    assert b'"value">2</div>' in response.data


def test_dashboard_shows_recently_added_stock(admin_client, app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol", low_stock_threshold=100)
        make_batch(medicine_id, "Tablet", 10, expiry_date="2030-01-01",
                   cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)

    response = admin_client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Recently Added Stock" in body
    assert "Cetamol" in body
    assert "2030-01-01" in body


def test_dashboard_hides_recent_stock_section_when_none_added(admin_client, app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")

    response = admin_client.get("/")
    body = response.get_data(as_text=True)
    assert "No stock has been added" in body
