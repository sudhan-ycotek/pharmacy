import functools

import click
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask.cli import with_appcontext
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db

bp = Blueprint("auth", __name__)


def create_user(username, password, role):
    db = get_db()
    cur = db.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
        (username, generate_password_hash(password), role),
    )
    db.commit()
    return cur.lastrowid


def verify_login(username, password):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        return None
    return user


def current_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)
    return wrapped_view


def role_required(*roles):
    def decorator(view):
        @functools.wraps(view)
        @login_required
        def wrapped_view(**kwargs):
            if session.get("role") not in roles:
                abort(403)
            return view(**kwargs)
        return wrapped_view
    return decorator


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = verify_login(username, password)
        if user is None:
            flash("Invalid username or password")
        else:
            session.clear()
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard.home"))
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@click.command("init-admin")
@click.argument("username")
@click.argument("password")
@with_appcontext
def init_admin_command(username, password):
    create_user(username, password, "admin")
    click.echo(f"Admin user '{username}' created.")
