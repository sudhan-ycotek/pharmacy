import sqlite3

from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(schema_path):
    db = get_db()
    with open(schema_path) as f:
        db.executescript(f.read())
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
