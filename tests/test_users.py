import pytest

from auth import create_user
from users import delete_staff, list_staff


def test_list_staff_returns_only_staff_role(app):
    with app.app_context():
        create_user("admin", "pw", "admin")
        create_user("staff1", "pw", "staff")
        staff = list_staff()
        assert len(staff) == 1
        assert staff[0]["username"] == "staff1"


def test_delete_staff_removes_user(app):
    with app.app_context():
        user_id = create_user("staff1", "pw", "staff")
        delete_staff(user_id)
        assert list_staff() == []


def test_delete_staff_refuses_to_delete_admin(app):
    with app.app_context():
        admin_id = create_user("admin", "pw", "admin")
        with pytest.raises(ValueError):
            delete_staff(admin_id)


def test_users_route_requires_admin(staff_client):
    response = staff_client.get("/users")
    assert response.status_code == 403


def test_users_add_route_creates_staff(admin_client, app):
    response = admin_client.post("/users/add", data={"username": "newstaff", "password": "pw123"})
    assert response.status_code == 302
    with app.app_context():
        assert any(u["username"] == "newstaff" for u in list_staff())


def test_delete_staff_with_sales_history_raises_gracefully(app):
    """Deleting a staff account with sales history raises ValueError (IntegrityError becomes ValueError)"""
    with app.app_context():
        # Setup: create medicine and staff user
        from inventory import add_medicine, add_stock
        medicine_id = add_medicine("Paracetamol", "Tablet", 10, [
            {"unit_name": "Tablet", "qty_in_base_units": 1, "price": 5.0},
        ])
        add_stock(medicine_id, "Tablet", 100)

        staff_id = create_user("staff1", "pw", "staff")

        # Create a sale by this staff member
        from sales import create_sale
        create_sale(staff_id, [
            {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 10},
        ])

        # Verify the sale was created
        assert len(list_staff()) == 1

        # Attempt to delete the staff member should raise ValueError with clear message
        with pytest.raises(ValueError, match="cannot delete.*they have recorded sales"):
            delete_staff(staff_id)

        # Verify the staff member still exists
        assert len(list_staff()) == 1


def test_dashboard_shows_staff_accounts_link_for_admin(admin_client):
    """Admin dashboard shows Staff Accounts link"""
    response = admin_client.get("/")
    assert response.status_code == 200
    assert "Staff Accounts" in response.data.decode()
    assert "/users" in response.data.decode()


def test_dashboard_hides_staff_accounts_link_for_staff(staff_client):
    """Staff dashboard does not show Staff Accounts link"""
    response = staff_client.get("/")
    assert response.status_code == 200
    assert "Staff Accounts" not in response.data.decode()


def test_users_add_duplicate_username_returns_gracefully(admin_client, app):
    """POSTing duplicate username to /users/add returns redirect with flash, not 500"""
    # First create a staff account
    response1 = admin_client.post("/users/add", data={"username": "duplicate", "password": "pw123"})
    assert response1.status_code == 302

    # Attempt to create another with same username
    response2 = admin_client.post("/users/add", data={"username": "duplicate", "password": "pw456"})
    assert response2.status_code == 302  # Should redirect, not 500

    # Verify only one staff account with that username exists
    with app.app_context():
        staff = list_staff()
        assert len([s for s in staff if s["username"] == "duplicate"]) == 1


def test_users_delete_with_invalid_id_returns_gracefully(admin_client):
    """POSTing delete for non-existent user returns redirect with flash, not 500"""
    response = admin_client.post("/users/999/delete")
    assert response.status_code == 302  # Should redirect, not 500
