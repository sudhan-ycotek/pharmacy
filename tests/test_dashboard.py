from inventory import add_medicine, add_stock
from auth import create_user
from sales import create_sale

TABLET_UNITS = [
    {"unit_name": "Box", "qty_in_base_units": 240, "price": 480.0},
    {"unit_name": "Tablet", "qty_in_base_units": 1, "price": 2.5},
]


def test_dashboard_shows_low_stock(admin_client, app):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 100, TABLET_UNITS)
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
        medicine_id = add_medicine("Napa", "Tablet", 100, TABLET_UNITS)
        add_stock(medicine_id, "Tablet", 100)
        user_id = create_user("cashier1", "pw", "staff")
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])

    response = admin_client.get("/")
    assert response.status_code == 200
    assert b"10.00" in response.data  # 4 tablets * 2.5 price = 10.00
