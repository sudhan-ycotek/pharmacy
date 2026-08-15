import os
import secrets
import shutil
import sys
import time

from flask import Flask

import auth
import dashboard
import db as db_module
import inventory
import photos
import purchases
import sales
import users
import vendors

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-built exe: bundled resources (templates, schema.sql,
    # the original static/ files) live in a temp extraction dir that vanishes when
    # the exe closes. Writable data (the DB, the secret key, uploaded photos) must
    # live next to the exe itself so it survives between runs.
    BUNDLE_DIR = sys._MEIPASS
    DATA_DIR = os.path.dirname(sys.executable)
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = BUNDLE_DIR

TEMPLATE_DIR = os.path.join(BUNDLE_DIR, "templates")
STATIC_DIR = os.path.join(DATA_DIR, "static")
SECRET_KEY_PATH = os.path.join(DATA_DIR, "secret_key.txt")


def _ensure_static_dir():
    if not os.path.exists(STATIC_DIR):
        shutil.copytree(os.path.join(BUNDLE_DIR, "static"), STATIC_DIR)


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
    _ensure_static_dir()
    app = Flask(__name__, root_path=BUNDLE_DIR, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
    app.config.from_mapping(
        SECRET_KEY="dev-change-me" if test_config and test_config.get("TESTING") else _load_or_create_secret_key(),
        DATABASE=os.path.join(DATA_DIR, "pharmacy.db"),
    )
    if test_config:
        app.config.update(test_config)

    db_module.init_app(app)

    with app.app_context():
        if not os.path.exists(app.config["DATABASE"]):
            db_module.init_db(os.path.join(BUNDLE_DIR, "schema.sql"))

    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(inventory.bp)
    app.register_blueprint(photos.bp)
    app.register_blueprint(purchases.bp)
    app.register_blueprint(sales.bp)
    app.register_blueprint(users.bp)
    app.register_blueprint(vendors.bp)
    app.cli.add_command(auth.init_admin_command)
    app.cli.add_command(auth.reset_admin_password_command)

    return app


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # A packaged exe has no `flask` command available — dispatch CLI
        # subcommands (init-admin, reset-admin-password) directly instead.
        # The commands are decorated with @with_appcontext, which otherwise
        # tries to rediscover an app via Flask's own CLI machinery; pushing
        # a context up front short-circuits that and reuses this instance.
        app = create_app()
        with app.app_context():
            app.cli.main(args=sys.argv[1:], prog_name=os.path.basename(sys.argv[0]))
    else:
        if getattr(sys, "frozen", False):
            # A windowed (--noconsole) PyInstaller build has no real stdout/stderr —
            # Werkzeug's startup banner would crash trying to write to None.
            if sys.stdout is None:
                sys.stdout = open(os.devnull, "w")
            if sys.stderr is None:
                sys.stderr = open(os.devnull, "w")

        import socket
        import threading

        import webview

        app = create_app()

        def _run_server():
            # use_reloader=False is required: the reloader re-execs the process,
            # which would spawn a second webview window.
            app.run(host="0.0.0.0", port=5000, use_reloader=False)

        threading.Thread(target=_run_server, daemon=True).start()

        # Poll instead of a fixed sleep -- more robust than a hardcoded delay on a
        # slow/cold onefile extraction.
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", 5000), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)

        webview.create_window(
            "Pharmacy Inventory", "http://127.0.0.1:5000",
            width=1280, height=800, min_size=(1024, 700),
        )
        webview.start()
