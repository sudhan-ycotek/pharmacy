from inventory import add_medicine, add_stock

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
