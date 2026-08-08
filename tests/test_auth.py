from auth import create_user, verify_login


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
