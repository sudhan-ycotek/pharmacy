from auth import create_user
from sales import create_sale, void_sale
from helpers import make_box_file_medicine, make_stock


def test_dashboard_shows_low_stock(admin_client, app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol", low_stock_threshold=100)
        make_stock(medicine_id, "Tablet", 10, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)  # below threshold of 100

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
        make_stock(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        user_id = create_user("cashier1", "pw", "staff")
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])

    response = admin_client.get("/")
    assert response.status_code == 200
    assert b"10.00" in response.data  # 4 tablets * 2.5 price = 10.00


def test_dashboard_shows_items_in_stock(admin_client, app):
    with app.app_context():
        m1 = make_box_file_medicine(name="Cetamol")
        m2 = make_box_file_medicine(name="Napa")
        make_stock(m1, "Box", 2, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)
        make_stock(m2, "Box", 3, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)

    response = admin_client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Items In Stock" in body
    assert f'"value">{(2 + 3) * 240}</div>' in body


def test_dashboard_shows_recently_added_stock(admin_client, app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol", low_stock_threshold=100)
        make_stock(medicine_id, "Tablet", 10, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)

    response = admin_client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Recently Added Stock" in body
    assert "Cetamol" in body


def test_dashboard_hides_recent_stock_section_when_none_added(admin_client, app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")

    response = admin_client.get("/")
    body = response.get_data(as_text=True)
    assert "No stock has been added" in body


def test_dashboard_shows_items_sold_today(admin_client, app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Napa", low_stock_threshold=100)
        make_stock(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        user_id = create_user("cashier1", "pw", "staff")
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])

    response = admin_client.get("/")
    body = response.get_data(as_text=True)
    assert "Items Sold" in body
    assert '"value">4</div>' in body


def test_dashboard_profit_made_admin_only(app, client):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Napa", low_stock_threshold=100)
        make_stock(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        create_user("boss", "bosspass", "admin")
        owner_id = create_user("owner", "ownerpass", "staff")
        create_sale(owner_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])

    client.post("/login", data={"username": "owner", "password": "ownerpass"})
    staff_body = client.get("/").get_data(as_text=True)
    assert "Profit Made" not in staff_body
    client.post("/logout")

    client.post("/login", data={"username": "boss", "password": "bosspass"})
    admin_body = client.get("/").get_data(as_text=True)
    assert "Profit Made" in admin_body


def test_dashboard_stock_card_shows_this_month_delta(admin_client, app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol")
        make_stock(medicine_id, "Box", 3, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)

    body = admin_client.get("/").get_data(as_text=True)
    assert f"+{3 * 240} this month" in body


def test_dashboard_renders_sparkline_polylines(admin_client, app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Napa", low_stock_threshold=100)
        make_stock(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        user_id = create_user("cashier1", "pw", "staff")
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])

    body = admin_client.get("/").get_data(as_text=True)
    assert 'polyline points="' in body


def test_dashboard_does_not_show_expiry_list_widget(admin_client, app):
    """Batch/expiry tracking was removed -- the dashboard must not reference it."""
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Cetamol")
        make_stock(medicine_id, "Tablet", 10, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.0)

    body = admin_client.get("/").get_data(as_text=True)
    assert "Expiry List" not in body


def test_dashboard_low_stock_shows_last_restock_column(admin_client, app):
    with app.app_context():
        from inventory import low_stock_medicines
        medicine_id = make_box_file_medicine(name="Cetamol", low_stock_threshold=100)
        make_stock(medicine_id, "Tablet", 10, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        last_restock = low_stock_medicines()[0]["last_restock"]

    body = admin_client.get("/").get_data(as_text=True)
    assert "Last Restock" in body
    assert last_restock in body


def test_dashboard_shows_recent_transactions_and_view_all_link(admin_client, app):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Napa", low_stock_threshold=1000)
        make_stock(medicine_id, "Tablet", 1000, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        user_id = create_user("cashier1", "pw", "staff")
        for _ in range(6):
            create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])

    body = admin_client.get("/").get_data(as_text=True)
    assert "Recent Transactions" in body
    assert body.count("Receipt</a>") == 5
    assert '/sales"' in body or "/sales'" in body


def test_dashboard_recent_transactions_filtered_by_role(app, client):
    with app.app_context():
        medicine_id = make_box_file_medicine(name="Napa", low_stock_threshold=100)
        make_stock(medicine_id, "Tablet", 100, cost_price_per_base_unit=1.0, mrp_per_base_unit=2.5)
        create_user("boss", "bosspass", "admin")
        owner_id = create_user("owner", "ownerpass", "staff")
        create_user("other", "otherpass", "staff")
        create_sale(owner_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])

    client.post("/login", data={"username": "other", "password": "otherpass"})
    other_body = client.get("/").get_data(as_text=True)
    assert "owner" not in other_body
    client.post("/logout")

    client.post("/login", data={"username": "boss", "password": "bosspass"})
    admin_body = client.get("/").get_data(as_text=True)
    assert "owner" in admin_body
