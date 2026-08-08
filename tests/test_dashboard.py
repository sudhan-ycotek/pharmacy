from inventory import add_stock
from auth import create_user
from sales import create_sale
from helpers import make_box_file_medicine


def test_dashboard_shows_low_stock(admin_client, app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol", low_stock_threshold=100)
        add_stock(medicine_id, "Tablet", 10)  # below threshold of 100

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
        add_stock(medicine_id, "Tablet", 100)
        user_id = create_user("cashier1", "pw", "staff")
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])

    response = admin_client.get("/")
    assert response.status_code == 200
    assert b"10.00" in response.data  # 4 tablets * 2.5 price = 10.00
