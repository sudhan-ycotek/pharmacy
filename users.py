from flask import Blueprint, redirect, render_template, request, url_for

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
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()


@bp.route("")
@role_required("admin")
def list_users():
    return render_template("users.html", staff=list_staff())


@bp.route("/add", methods=["POST"])
@role_required("admin")
def add_user():
    create_user(request.form["username"], request.form["password"], "staff")
    return redirect(url_for("users.list_users"))


@bp.route("/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def delete_user(user_id):
    delete_staff(user_id)
    return redirect(url_for("users.list_users"))
