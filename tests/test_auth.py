import pytest
from auth import create_user, verify_login, change_own_password, reset_admin_password


def test_create_user_and_verify_login(app):
    with app.app_context():
        create_user("admin", "secret123", "admin")
        user = verify_login("admin", "secret123")
        assert user is not None
        assert user["role"] == "admin"


def test_verify_login_rejects_wrong_password(app):
    with app.app_context():
        create_user("admin", "secret123", "admin")
        assert verify_login("admin", "wrongpass") is None


def test_login_route_shows_error_on_bad_credentials(client, app):
    with app.app_context():
        create_user("staff1", "staffpass", "staff")
    response = client.post(
        "/login", data={"username": "staff1", "password": "wrong"}
    )
    assert response.status_code == 200
    assert b"Invalid username or password" in response.data


def test_change_own_password_succeeds_with_correct_current_password(app):
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "oldpass", "staff")
        change_own_password(user_id, "oldpass", "newpass123")
        from auth import verify_login
        assert verify_login("staff1", "newpass123") is not None
        assert verify_login("staff1", "oldpass") is None


def test_change_own_password_rejects_wrong_current_password(app):
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "oldpass", "staff")
        with pytest.raises(ValueError):
            change_own_password(user_id, "wrongpass", "newpass123")


def test_change_password_route_requires_login(client):
    response = client.get("/change-password")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_change_password_route_updates_password(staff_client):
    response = staff_client.post("/change-password", data={
        "current_password": "staffpass",
        "new_password": "newstaffpass123",
    })
    assert response.status_code == 302


def test_reset_admin_password_updates_password(app):
    with app.app_context():
        create_user("admin", "oldpass", "admin")
        reset_admin_password("admin", "newpass123")
        assert verify_login("admin", "newpass123") is not None
        assert verify_login("admin", "oldpass") is None


def test_reset_admin_password_refuses_staff_target(app):
    with app.app_context():
        create_user("staff1", "pw", "staff")
        with pytest.raises(ValueError):
            reset_admin_password("staff1", "newpass123")


def test_reset_admin_password_refuses_unknown_user(app):
    with app.app_context():
        with pytest.raises(ValueError):
            reset_admin_password("nobody", "newpass123")
