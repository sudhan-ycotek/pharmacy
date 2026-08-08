import io
import os
import socket
import uuid
from datetime import datetime, timedelta

import qrcode
from flask import Blueprint, Response, current_app, jsonify, render_template, request

from auth import role_required
from db import get_db

bp = Blueprint("photos", __name__, url_prefix="/photos")

TOKEN_LIFETIME_MINUTES = 10
PORT = 5000


def create_photo_token():
    token = uuid.uuid4().hex
    expires_at = (datetime.utcnow() + timedelta(minutes=TOKEN_LIFETIME_MINUTES)).isoformat()
    db = get_db()
    db.execute(
        "INSERT INTO photo_tokens (token, photo_path, expires_at, used) VALUES (?, NULL, ?, 0)",
        (token, expires_at),
    )
    db.commit()
    return {"token": token, "expires_at": expires_at}


def is_token_valid(token):
    db = get_db()
    row = db.execute("SELECT * FROM photo_tokens WHERE token = ?", (token,)).fetchone()
    if row is None or row["used"]:
        return False
    return datetime.fromisoformat(row["expires_at"]) > datetime.utcnow()


def get_token_photo(token):
    db = get_db()
    row = db.execute("SELECT photo_path FROM photo_tokens WHERE token = ?", (token,)).fetchone()
    return row["photo_path"] if row else None


def save_photo(token, file_storage):
    if not is_token_valid(token):
        raise ValueError(f"invalid or expired token '{token}'")

    ext = os.path.splitext(file_storage.filename or "")[1].lower() or ".jpg"
    allowed_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    if ext not in allowed_exts:
        raise ValueError(f"unsupported file type '{ext}' — allowed types: {', '.join(sorted(allowed_exts))}")

    filename = f"{token}{ext}"
    photos_dir = os.path.join(current_app.static_folder, "photos")
    os.makedirs(photos_dir, exist_ok=True)
    filepath = os.path.join(photos_dir, filename)
    file_storage.save(filepath)

    relative_path = f"photos/{filename}"
    db = get_db()
    db.execute(
        "UPDATE photo_tokens SET photo_path = ?, used = 1 WHERE token = ?",
        (relative_path, token),
    )
    db.commit()
    return relative_path


def get_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


@bp.route("/new-token", methods=["POST"])
@role_required("admin")
def new_token():
    token_data = create_photo_token()
    lan_ip = get_lan_ip()
    upload_url = f"http://{lan_ip}:{PORT}/photos/upload/{token_data['token']}"
    return jsonify({
        "token": token_data["token"],
        "upload_url": upload_url,
        "qr_url": f"/photos/qr/{token_data['token']}.png",
    })


@bp.route("/qr/<token>.png")
@role_required("admin")
def qr_image(token):
    lan_ip = get_lan_ip()
    upload_url = f"http://{lan_ip}:{PORT}/photos/upload/{token}"
    img = qrcode.make(upload_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


@bp.route("/upload/<token>", methods=["GET", "POST"])
def upload(token):
    if request.method == "POST":
        if not is_token_valid(token):
            return "This link has expired. Ask for a new QR code.", 400
        try:
            file_storage = request.files["photo"]
            save_photo(token, file_storage)
            return render_template("upload_photo.html", token=token, done=True)
        except ValueError as e:
            return render_template("upload_photo.html", token=token, done=False, error=str(e))
    return render_template("upload_photo.html", token=token, done=False)


@bp.route("/status/<token>")
def status(token):
    photo_path = get_token_photo(token)
    return jsonify({"uploaded": photo_path is not None, "photo_path": photo_path})
