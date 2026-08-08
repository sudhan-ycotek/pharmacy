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
