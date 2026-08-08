import os
import secrets

from flask import Flask

import auth
import dashboard
import db as db_module
import inventory
import photos
import sales
import users

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_KEY_PATH = os.path.join(BASE_DIR, "secret_key.txt")


def _load_or_create_secret_key():
    """Read the persisted secret key, generating and saving one on first run.

    A hardcoded key would let anyone forge a signed session cookie, so each
    deployment gets its own random key stored beside pharmacy.db.
    """
    if os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH) as f:
            key = f.read().strip()
        if key:
            return key
    key = secrets.token_hex(32)
    with open(SECRET_KEY_PATH, "w") as f:
        f.write(key)
    return key


def create_app(test_config=None):
    app = Flask(__name__, root_path=BASE_DIR)
    app.config.from_mapping(
        SECRET_KEY="dev-change-me" if test_config and test_config.get("TESTING") else _load_or_create_secret_key(),
        DATABASE=os.path.join(BASE_DIR, "pharmacy.db"),
    )
    if test_config:
        app.config.update(test_config)

    db_module.init_app(app)

    with app.app_context():
        if not os.path.exists(app.config["DATABASE"]):
            db_module.init_db(os.path.join(BASE_DIR, "schema.sql"))

    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(inventory.bp)
    app.register_blueprint(photos.bp)
    app.register_blueprint(sales.bp)
    app.register_blueprint(users.bp)
    app.cli.add_command(auth.init_admin_command)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000)
