import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from auth import create_user, role_required
from db import get_db

bp = Blueprint("users", __name__, url_prefix="/users")


def list_staff():
    db = get_db()
    return db.execute("SELECT * FROM users WHERE role = 'staff' ORDER BY username").fetchall()


def delete_staff(user_id):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        raise ValueError(f"user {user_id} not found")
    if user["role"] != "staff":
        raise ValueError("only staff accounts can be deleted here")
    try:
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"cannot delete '{user['username']}' — they have recorded sales; consider keeping the account instead")


def reset_staff_password(user_id, new_password):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        raise ValueError(f"user {user_id} not found")
    if user["role"] != "staff":
        raise ValueError("only staff account passwords can be reset here")
    if not new_password:
        raise ValueError("new password cannot be empty")
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user_id),
    )
    db.commit()


@bp.route("")
@role_required("admin")
def list_users():
    return render_template("users.html", staff=list_staff())


@bp.route("/add", methods=["POST"])
@role_required("admin")
def add_user():
    try:
        username = request.form["username"]
        password = request.form["password"]
        create_user(username, password, "staff")
        return redirect(url_for("users.list_users"))
    except sqlite3.IntegrityError:
        flash(f"username '{request.form.get('username', '')}' is already taken")
    except (KeyError, ValueError) as e:
        flash(str(e))
    return redirect(url_for("users.list_users"))


@bp.route("/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def delete_user(user_id):
    try:
        delete_staff(user_id)
    except ValueError as e:
        flash(str(e))
    return redirect(url_for("users.list_users"))


@bp.route("/<int:user_id>/reset-password", methods=["POST"])
@role_required("admin")
def reset_password(user_id):
    try:
        reset_staff_password(user_id, request.form.get("new_password", ""))
        flash("Password reset.")
    except ValueError as e:
        flash(str(e))
    return redirect(url_for("users.list_users"))
