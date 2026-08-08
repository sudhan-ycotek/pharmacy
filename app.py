import os

from flask import Flask

import db as db_module

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_app(test_config=None):
    app = Flask(__name__, root_path=BASE_DIR)
    app.config.from_mapping(
        SECRET_KEY="dev-change-me",
        DATABASE=os.path.join(BASE_DIR, "pharmacy.db"),
    )
    if test_config:
        app.config.update(test_config)

    db_module.init_app(app)

    with app.app_context():
        if not os.path.exists(app.config["DATABASE"]):
            db_module.init_db(os.path.join(BASE_DIR, "schema.sql"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
