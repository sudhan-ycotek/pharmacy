import io
import time

import pytest

from photos import create_photo_token, get_token_photo, is_token_valid, save_photo


def test_create_photo_token_is_valid_immediately(app):
    with app.app_context():
        token_data = create_photo_token()
        assert is_token_valid(token_data["token"]) is True


def test_is_token_valid_false_for_unknown_token(app):
    with app.app_context():
        assert is_token_valid("does-not-exist") is False


def test_save_photo_marks_token_used_and_stores_path(app):
    with app.app_context():
        token_data = create_photo_token()
        fake_file = (io.BytesIO(b"fake image bytes"), "photo.jpg")
        from werkzeug.datastructures import FileStorage
        file_storage = FileStorage(stream=fake_file[0], filename=fake_file[1])
        path = save_photo(token_data["token"], file_storage)
        assert path.endswith(".jpg")
        assert get_token_photo(token_data["token"]) == path
        assert is_token_valid(token_data["token"]) is False  # used, no longer valid


def test_save_photo_rejects_invalid_token(app):
    with app.app_context():
        from werkzeug.datastructures import FileStorage
        file_storage = FileStorage(stream=io.BytesIO(b"x"), filename="photo.jpg")
        with pytest.raises(ValueError):
            save_photo("bad-token", file_storage)


def test_new_token_route_returns_token_and_qr_url(admin_client):
    response = admin_client.post("/photos/new-token")
    assert response.status_code == 200
    data = response.get_json()
    assert "token" in data
    assert "qr_url" in data
    assert "upload_url" in data


def test_status_route_reports_uploaded_state(admin_client, app):
    with app.app_context():
        token_data = create_photo_token()
    response = admin_client.get(f"/photos/status/{token_data['token']}")
    assert response.status_code == 200
    assert response.get_json()["uploaded"] is False


def test_expired_token_is_invalid(app):
    with app.app_context():
        from datetime import datetime, timedelta
        from db import get_db
        token_data = create_photo_token()
        db = get_db()
        past_time = (datetime.utcnow() - timedelta(minutes=1)).isoformat()
        db.execute("UPDATE photo_tokens SET expires_at = ? WHERE token = ?", (past_time, token_data["token"]))
        db.commit()
        assert is_token_valid(token_data["token"]) is False


def test_status_route_reports_uploaded_after_save(admin_client, app):
    with app.app_context():
        token_data = create_photo_token()
        fake_file = (io.BytesIO(b"fake image bytes"), "photo.jpg")
        from werkzeug.datastructures import FileStorage
        file_storage = FileStorage(stream=fake_file[0], filename=fake_file[1])
        save_photo(token_data["token"], file_storage)
    response = admin_client.get(f"/photos/status/{token_data['token']}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["uploaded"] is True
    assert data["photo_path"] is not None


def test_save_photo_rejects_invalid_file_type(app):
    with app.app_context():
        token_data = create_photo_token()
        from werkzeug.datastructures import FileStorage
        file_storage = FileStorage(stream=io.BytesIO(b"<html>malicious</html>"), filename="photo.html")
        with pytest.raises(ValueError, match="unsupported file type"):
            save_photo(token_data["token"], file_storage)


def test_new_token_route_requires_admin(client):
    response = client.post("/photos/new-token")
    assert response.status_code in (302, 401)  # redirect to login or unauthorized
