# Pharmacy Inventory & Billing System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local (LAN-only, no internet) Flask + SQLite web app for a pharmacy to manage medicine stock (with variable box/file/tablet-style packaging), record sales with printable receipts, and let staff upload medicine photos from their phone via a QR-code handoff.

**Architecture:** Flat directory of small Flask blueprint modules (`auth`, `inventory`, `sales`, `dashboard`, `users`, `photos`), each owning its own routes + business-logic functions, sharing one SQLite connection helper (`db.py`). Server-rendered Jinja2 templates, minimal CSS, vanilla JS only for live search and photo-upload polling.

**Tech Stack:** Python 3, Flask, SQLite (stdlib `sqlite3`), Werkzeug (password hashing, bundled with Flask), `qrcode` + `Pillow` (QR generation), pytest (testing).

## Global Constraints

- Runs entirely offline/LAN — no external services, no CDN assets, no internet calls of any kind.
- Single SQLite file `pharmacy.db` is the entire database — no separate DB server.
- No JS framework. Vanilla JS only for: live medicine search on the sale screen, background polling on the photo-upload flow, and "add another unit row" on the add-medicine form.
- UI is intentionally basic — plain HTML forms/tables, minimal CSS, no visual polish beyond readability.
- No batch/expiry tracking, no supplier tracking — explicitly out of scope for this version.
- Roles are exactly two: `admin` and `staff`, enforced server-side on every route (not just hidden in the UI).
- Money values are Python floats rounded to 2 decimals at every computation boundary (no Decimal — YAGNI for a small local shop).
- Stock is always stored/mutated in base units (the smallest packaging unit); every medicine must have exactly one unit row with `qty_in_base_units = 1`.

---

## File Structure

```
pharmacy_management_system/
  app.py                  # create_app() factory, blueprint registration, CLI command registration
  db.py                    # get_db()/init_db()/init_app() — sqlite connection helper
  schema.sql               # table definitions
  auth.py                  # password hashing, login/logout routes, login_required/role_required, init-admin CLI
  inventory.py             # medicine + unit CRUD, add_stock, low_stock_medicines, price breakdown, routes
  sales.py                 # create_sale/void_sale/today_sales_total/get_sale, new-sale + receipt routes
  dashboard.py             # home route combining low-stock + today's sales
  users.py                 # admin-only staff account management
  photos.py                # QR token lifecycle, mobile upload page, polling endpoint
  templates/
    base.html
    login.html
    dashboard.html
    medicines.html
    medicine_add.html
    add_stock.html
    new_sale.html
    receipt.html
    users.html
    upload_photo.html
  static/
    style.css
    photos/
      .gitkeep
  tests/
    conftest.py
    test_db.py
    test_auth.py
    test_inventory.py
    test_sales.py
    test_dashboard.py
    test_users.py
    test_photos.py
  requirements.txt
  run.bat
  README.md
  .gitignore
```

This refines the original spec's single `models.py` into one focused module per feature area (`auth`/`inventory`/`sales`/`dashboard`/`users`/`photos`), each pairing its business logic with its own Flask blueprint — keeps files small and each task's diff self-contained.

---

### Task 1: Project Scaffolding — DB layer, schema, app factory

**Files:**
- Create: `schema.sql`
- Create: `db.py`
- Create: `app.py`
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `tests/conftest.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `db.get_db() -> sqlite3.Connection` (row_factory=`sqlite3.Row`, foreign keys ON), `db.init_db(schema_path: str) -> None`, `db.init_app(app: Flask) -> None`
- Produces: `app.create_app(test_config: dict | None = None) -> Flask` — later tasks import this in their own tests and add blueprint registrations inside it.

- [ ] **Step 1: Write requirements.txt**

```
Flask>=3.0
qrcode>=7.4
Pillow>=10.0
pytest>=8.0
```

- [ ] **Step 2: Write .gitignore**

```
__pycache__/
*.pyc
pharmacy.db
static/photos/*.jpg
static/photos/*.png
!static/photos/.gitkeep
.pytest_cache/
```

- [ ] **Step 3: Write tests/conftest.py (sys.path fix + app/client fixtures)**

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    db_path = tmp_path / "test.db"
    return create_app({
        "TESTING": True,
        "DATABASE": str(db_path),
        "SECRET_KEY": "test",
    })


@pytest.fixture
def client(app):
    return app.test_client()
```

- [ ] **Step 4: Write the failing test**

```python
# tests/test_db.py
from db import get_db

EXPECTED_TABLES = {
    "users", "medicines", "medicine_units",
    "sales", "sale_items", "photo_tokens",
}


def test_init_db_creates_expected_tables(app):
    with app.app_context():
        conn = get_db()
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert EXPECTED_TABLES <= tables
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'` (or `'db'`)

- [ ] **Step 6: Write schema.sql**

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'staff'))
);

CREATE TABLE medicines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,
    photo_path TEXT,
    stock_in_base_units INTEGER NOT NULL DEFAULT 0,
    low_stock_threshold INTEGER NOT NULL DEFAULT 10
);

CREATE TABLE medicine_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    qty_in_base_units INTEGER NOT NULL,
    price REAL NOT NULL
);

CREATE TABLE sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    timestamp TEXT NOT NULL,
    total REAL NOT NULL,
    voided INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    subtotal REAL NOT NULL
);

CREATE TABLE photo_tokens (
    token TEXT PRIMARY KEY,
    photo_path TEXT,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
```

- [ ] **Step 7: Write db.py**

```python
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
```

- [ ] **Step 8: Write app.py**

```python
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
```

- [ ] **Step 9: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add schema.sql db.py app.py requirements.txt .gitignore tests/conftest.py tests/test_db.py
git commit -m "feat: add DB schema, connection helper, and app factory"
```

---

### Task 2: Auth — login/logout, roles, admin bootstrap

**Files:**
- Create: `auth.py`
- Create: `templates/base.html`
- Create: `templates/login.html`
- Create: `static/style.css`
- Modify: `app.py` (register `auth.bp`, add `init-admin` CLI command)
- Modify: `tests/conftest.py` (add `admin_user`/`staff_user`/`admin_client`/`staff_client` fixtures)
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `db.get_db()` from Task 1.
- Produces: `auth.create_user(username: str, password: str, role: str) -> int`, `auth.verify_login(username: str, password: str) -> sqlite3.Row | None`, `auth.current_user() -> sqlite3.Row | None`, `auth.login_required(view)`, `auth.role_required(*roles: str)`, `auth.bp` (Blueprint, routes `auth.login`/`auth.logout`), CLI command `init-admin USERNAME PASSWORD`. Every later blueprint imports `login_required`/`role_required`/`current_user` from `auth`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_auth.py
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


def test_login_route_sets_session_and_redirects(client, app):
    with app.app_context():
        create_user("staff1", "staffpass", "staff")
    response = client.post(
        "/login", data={"username": "staff1", "password": "staffpass"}
    )
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["role"] == "staff"


def test_login_route_shows_error_on_bad_credentials(client, app):
    with app.app_context():
        create_user("staff1", "staffpass", "staff")
    response = client.post(
        "/login", data={"username": "staff1", "password": "wrong"}
    )
    assert response.status_code == 200
    assert b"Invalid username or password" in response.data


def test_dashboard_redirects_to_login_when_not_authenticated(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth'` (the last test also needs `dashboard.home`, added in Task 5 — for now expect the whole file to error on collection)

- [ ] **Step 3: Write auth.py**

```python
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
```

- [ ] **Step 4: Write templates/base.html**

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Pharmacy Inventory{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  {% if session.get('user_id') %}
  <nav>
    <a href="{{ url_for('dashboard.home') }}">Dashboard</a>
    <span class="user-info">{{ session.get('username') }} ({{ session.get('role') }})</span>
    <form method="post" action="{{ url_for('auth.logout') }}" class="inline-form">
      <button type="submit">Logout</button>
    </form>
  </nav>
  {% endif %}
  {% for message in get_flashed_messages() %}
    <p class="flash">{{ message }}</p>
  {% endfor %}
  <main>
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 5: Write templates/login.html**

```html
{% extends "base.html" %}
{% block title %}Login{% endblock %}
{% block content %}
<h1>Pharmacy Login</h1>
<form method="post">
  <label>Username <input type="text" name="username" required autofocus></label>
  <label>Password <input type="password" name="password" required></label>
  <button type="submit">Log In</button>
</form>
{% endblock %}
```

- [ ] **Step 6: Write static/style.css**

```css
body { font-family: sans-serif; margin: 0; padding: 0 1rem; }
nav { display: flex; align-items: center; gap: 1rem; padding: 0.5rem 0; border-bottom: 1px solid #ccc; }
nav .user-info { margin-left: auto; }
.inline-form { display: inline; }
.flash { background: #ffe9a8; padding: 0.5rem; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
th, td { border: 1px solid #ccc; padding: 0.4rem; text-align: left; }
label { display: block; margin: 0.5rem 0; }
.low-stock { color: #a00; font-weight: bold; }
@media print {
  nav, .no-print { display: none; }
}
```

- [ ] **Step 7: Modify app.py — register auth blueprint and CLI command**

```python
# add near the top, after `import db as db_module`
import auth
```

```python
# inside create_app(), after db_module.init_db(...) block, before `return app`
    app.register_blueprint(auth.bp)
    app.cli.add_command(auth.init_admin_command)

    return app
```

- [ ] **Step 8: Modify tests/conftest.py — add auth fixtures**

```python
# append to tests/conftest.py
from auth import create_user


@pytest.fixture
def admin_user(app):
    with app.app_context():
        create_user("admin", "adminpass", "admin")


@pytest.fixture
def staff_user(app):
    with app.app_context():
        create_user("staff1", "staffpass", "staff")


@pytest.fixture
def admin_client(client, admin_user):
    client.post("/login", data={"username": "admin", "password": "adminpass"})
    return client


@pytest.fixture
def staff_client(client, staff_user):
    client.post("/login", data={"username": "staff1", "password": "staffpass"})
    return client
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/test_auth.py -v`
Expected: 4 of 5 PASS; `test_dashboard_redirects_to_login_when_not_authenticated` still FAILs with a 404 (no `/` route yet — `dashboard.home` doesn't exist until Task 5)

- [ ] **Step 10: Delete the dashboard-redirect test for now — it belongs to Task 5**

Remove `test_dashboard_redirects_to_login_when_not_authenticated` from `tests/test_auth.py`. It will be re-added as part of Task 5's test file once the `/` route exists.

- [ ] **Step 11: Run tests to verify they pass**

Run: `pytest tests/test_auth.py -v`
Expected: PASS (4 tests)

- [ ] **Step 12: Commit**

```bash
git add auth.py templates/base.html templates/login.html static/style.css app.py tests/conftest.py tests/test_auth.py
git commit -m "feat: add login/logout, roles, and admin bootstrap CLI"
```

---

### Task 3: Inventory — medicines, variable packaging units, stock

**Files:**
- Create: `inventory.py`
- Create: `templates/medicines.html`
- Create: `templates/medicine_add.html`
- Create: `templates/add_stock.html`
- Modify: `app.py` (register `inventory.bp`)
- Test: `tests/test_inventory.py`

**Interfaces:**
- Consumes: `db.get_db()`, `auth.role_required`, `auth.login_required`.
- Produces: `inventory.add_medicine(name, category, low_stock_threshold, units) -> int`, `inventory.list_medicines() -> list[Row]`, `inventory.get_medicine(medicine_id) -> Row | None`, `inventory.get_medicine_units(medicine_id) -> list[Row]`, `inventory.search_medicines(query) -> list[Row]`, `inventory.add_stock(medicine_id, unit_name, quantity) -> int`, `inventory.low_stock_medicines() -> list[Row]`, `inventory.unit_price_breakdown(medicine_id) -> list[dict]`. Route names: `inventory.list_medicines_view`, `inventory.add_medicine_view`, `inventory.add_stock_view`. Task 4 (`sales.py`) calls `inventory.get_medicine_units` and reads `medicine_units` directly for pricing/stock checks.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_inventory.py
import pytest

from inventory import (
    add_medicine,
    add_stock,
    get_medicine_units,
    list_medicines,
    low_stock_medicines,
    search_medicines,
    unit_price_breakdown,
)

TABLET_UNITS = [
    {"unit_name": "Box", "qty_in_base_units": 240, "price": 480.0},
    {"unit_name": "File", "qty_in_base_units": 20, "price": 45.0},
    {"unit_name": "Tablet", "qty_in_base_units": 1, "price": 2.5},
]

LIQUID_UNITS = [
    {"unit_name": "Bottle", "qty_in_base_units": 1, "price": 120.0},
]


def test_add_medicine_requires_exactly_one_base_unit(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "Tablet", 10, [
                {"unit_name": "Box", "qty_in_base_units": 240, "price": 480.0},
            ])


def test_add_medicine_with_multi_level_units(app):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        units = get_medicine_units(medicine_id)
        assert [u["unit_name"] for u in units] == ["Tablet", "File", "Box"]


def test_add_medicine_with_single_unit(app):
    with app.app_context():
        medicine_id = add_medicine("Cough Syrup", "Liquid", 5, LIQUID_UNITS)
        units = get_medicine_units(medicine_id)
        assert len(units) == 1
        assert units[0]["unit_name"] == "Bottle"


def test_add_stock_converts_to_base_units(app):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        new_total = add_stock(medicine_id, "Box", 2)
        assert new_total == 480


def test_add_stock_unknown_unit_raises(app):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Pallet", 1)


def test_low_stock_medicines_flags_below_threshold(app):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        add_stock(medicine_id, "Tablet", 10)
        low = low_stock_medicines()
        assert any(m["id"] == medicine_id for m in low)


def test_unit_price_breakdown_computes_price_per_base_unit(app):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        breakdown = unit_price_breakdown(medicine_id)
        by_unit = {b["unit_name"]: b for b in breakdown}
        assert by_unit["Box"]["price_per_base_unit"] == 2.0
        assert by_unit["Tablet"]["price_per_base_unit"] == 2.5


def test_search_medicines_matches_by_name(app):
    with app.app_context():
        add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        add_medicine("Napa Extra", "Tablet", 50, TABLET_UNITS)
        results = search_medicines("ceta")
        assert len(results) == 1
        assert results[0]["name"] == "Cetamol"


def test_list_medicines_returns_all(app):
    with app.app_context():
        add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        add_medicine("Cough Syrup", "Liquid", 5, LIQUID_UNITS)
        assert len(list_medicines()) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_inventory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'inventory'`

- [ ] **Step 3: Write inventory.py**

```python
from flask import Blueprint, redirect, render_template, request, url_for

from auth import role_required
from db import get_db

bp = Blueprint("inventory", __name__, url_prefix="/medicines")


def add_medicine(name, category, low_stock_threshold, units):
    if not units:
        raise ValueError("medicine must have at least one unit")
    base_units = [u for u in units if u["qty_in_base_units"] == 1]
    if len(base_units) != 1:
        raise ValueError("medicine must have exactly one base unit (qty_in_base_units = 1)")

    db = get_db()
    cur = db.execute(
        "INSERT INTO medicines (name, category, stock_in_base_units, low_stock_threshold) "
        "VALUES (?, ?, 0, ?)",
        (name, category, low_stock_threshold),
    )
    medicine_id = cur.lastrowid
    for u in units:
        db.execute(
            "INSERT INTO medicine_units (medicine_id, unit_name, qty_in_base_units, price) "
            "VALUES (?, ?, ?, ?)",
            (medicine_id, u["unit_name"], u["qty_in_base_units"], u["price"]),
        )
    db.commit()
    return medicine_id


def list_medicines():
    db = get_db()
    return db.execute("SELECT * FROM medicines ORDER BY name").fetchall()


def get_medicine(medicine_id):
    db = get_db()
    return db.execute("SELECT * FROM medicines WHERE id = ?", (medicine_id,)).fetchone()


def get_medicine_units(medicine_id):
    db = get_db()
    return db.execute(
        "SELECT * FROM medicine_units WHERE medicine_id = ? ORDER BY qty_in_base_units ASC",
        (medicine_id,),
    ).fetchall()


def search_medicines(query):
    db = get_db()
    return db.execute(
        "SELECT * FROM medicines WHERE name LIKE ? ORDER BY name",
        (f"%{query}%",),
    ).fetchall()


def add_stock(medicine_id, unit_name, quantity):
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    db = get_db()
    unit_row = db.execute(
        "SELECT qty_in_base_units FROM medicine_units WHERE medicine_id = ? AND unit_name = ?",
        (medicine_id, unit_name),
    ).fetchone()
    if unit_row is None:
        raise ValueError(f"unknown unit '{unit_name}' for medicine {medicine_id}")
    base_units_added = unit_row["qty_in_base_units"] * quantity
    db.execute(
        "UPDATE medicines SET stock_in_base_units = stock_in_base_units + ? WHERE id = ?",
        (base_units_added, medicine_id),
    )
    db.commit()
    return db.execute(
        "SELECT stock_in_base_units FROM medicines WHERE id = ?", (medicine_id,)
    ).fetchone()["stock_in_base_units"]


def low_stock_medicines():
    db = get_db()
    return db.execute(
        "SELECT * FROM medicines WHERE stock_in_base_units < low_stock_threshold ORDER BY name"
    ).fetchall()


def unit_price_breakdown(medicine_id):
    return [
        {
            "unit_name": u["unit_name"],
            "price": u["price"],
            "price_per_base_unit": round(u["price"] / u["qty_in_base_units"], 2),
        }
        for u in get_medicine_units(medicine_id)
    ]


@bp.route("/")
@role_required("admin", "staff")
def list_medicines_view():
    return render_template("medicines.html", medicines=list_medicines())


@bp.route("/add", methods=["GET", "POST"])
@role_required("admin")
def add_medicine_view():
    if request.method == "POST":
        unit_names = request.form.getlist("unit_name")
        unit_qtys = request.form.getlist("unit_qty")
        unit_prices = request.form.getlist("unit_price")
        units = [
            {"unit_name": n, "qty_in_base_units": int(q), "price": float(p)}
            for n, q, p in zip(unit_names, unit_qtys, unit_prices)
            if n.strip()
        ]
        add_medicine(
            request.form["name"],
            request.form["category"],
            int(request.form["low_stock_threshold"]),
            units,
        )
        return redirect(url_for("inventory.list_medicines_view"))
    return render_template("medicine_add.html")


@bp.route("/<int:medicine_id>/add-stock", methods=["GET", "POST"])
@role_required("admin")
def add_stock_view(medicine_id):
    medicine = get_medicine(medicine_id)
    if request.method == "POST":
        add_stock(medicine_id, request.form["unit_name"], int(request.form["quantity"]))
        return redirect(url_for("inventory.list_medicines_view"))
    return render_template(
        "add_stock.html", medicine=medicine, units=get_medicine_units(medicine_id)
    )
```

- [ ] **Step 4: Write templates/medicines.html**

```html
{% extends "base.html" %}
{% block title %}Medicines{% endblock %}
{% block content %}
<h1>Medicines</h1>
{% if session.get('role') == 'admin' %}
<p><a href="{{ url_for('inventory.add_medicine_view') }}">+ Add Medicine</a></p>
{% endif %}
<table>
  <tr><th>Name</th><th>Category</th><th>Stock (base units)</th><th>Threshold</th><th></th></tr>
  {% for m in medicines %}
  <tr class="{{ 'low-stock' if m['stock_in_base_units'] < m['low_stock_threshold'] else '' }}">
    <td>{{ m['name'] }}</td>
    <td>{{ m['category'] }}</td>
    <td>{{ m['stock_in_base_units'] }}</td>
    <td>{{ m['low_stock_threshold'] }}</td>
    <td>
      {% if session.get('role') == 'admin' %}
      <a href="{{ url_for('inventory.add_stock_view', medicine_id=m['id']) }}">Add Stock</a>
      {% endif %}
    </td>
  </tr>
  {% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 5: Write templates/medicine_add.html**

```html
{% extends "base.html" %}
{% block title %}Add Medicine{% endblock %}
{% block content %}
<h1>Add Medicine</h1>
<form method="post">
  <label>Name <input type="text" name="name" required></label>
  <label>Category <input type="text" name="category"></label>
  <label>Low stock threshold <input type="number" name="low_stock_threshold" value="10" required></label>

  <h2>Packaging Units</h2>
  <p>Add one row per packaging level. Exactly one row must have quantity 1 (the smallest sellable unit).</p>
  <div id="units">
    <div class="unit-row">
      <input type="text" name="unit_name" placeholder="Unit name (e.g. Box)" required>
      <input type="number" name="unit_qty" placeholder="Qty in base units" required>
      <input type="number" step="0.01" name="unit_price" placeholder="Price" required>
    </div>
  </div>
  <button type="button" id="add-unit-row">+ Add another unit</button>
  <br><br>
  <button type="submit">Save Medicine</button>
</form>
<script>
document.getElementById("add-unit-row").addEventListener("click", function () {
  var container = document.getElementById("units");
  var row = container.firstElementChild.cloneNode(true);
  row.querySelectorAll("input").forEach(function (input) { input.value = ""; });
  container.appendChild(row);
});
</script>
{% endblock %}
```

- [ ] **Step 6: Write templates/add_stock.html**

```html
{% extends "base.html" %}
{% block title %}Add Stock{% endblock %}
{% block content %}
<h1>Add Stock — {{ medicine['name'] }}</h1>
<form method="post">
  <label>Unit
    <select name="unit_name" required>
      {% for u in units %}
      <option value="{{ u['unit_name'] }}">{{ u['unit_name'] }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Quantity <input type="number" name="quantity" min="1" required></label>
  <button type="submit">Add Stock</button>
</form>
{% endblock %}
```

- [ ] **Step 7: Modify app.py — register inventory blueprint**

```python
# add import near the top
import inventory
```

```python
# inside create_app(), after app.register_blueprint(auth.bp)
    app.register_blueprint(inventory.bp)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_inventory.py -v`
Expected: PASS (9 tests)

- [ ] **Step 9: Commit**

```bash
git add inventory.py templates/medicines.html templates/medicine_add.html templates/add_stock.html app.py tests/test_inventory.py
git commit -m "feat: add medicine catalog, variable packaging units, and stock management"
```

---

### Task 4: Sales — search, multi-item bill, stock decrement, void

**Files:**
- Create: `sales.py`
- Create: `templates/new_sale.html`
- Create: `templates/receipt.html`
- Modify: `app.py` (register `sales.bp`)
- Test: `tests/test_sales.py`

**Interfaces:**
- Consumes: `db.get_db()`, `auth.login_required`, `auth.role_required`, `auth.current_user`, `medicine_units` rows from Task 3.
- Produces: `sales.create_sale(user_id, items) -> dict` (`{"sale_id": int, "total": float}`), `sales.void_sale(sale_id) -> None`, `sales.today_sales_total() -> float`, `sales.get_sale(sale_id) -> dict | None` (`{"sale": Row, "items": list[Row]}`). Task 5 (`dashboard.py`) calls `sales.today_sales_total()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sales.py
import pytest

from inventory import add_medicine, get_medicine
from sales import create_sale, get_sale, today_sales_total, void_sale

TABLET_UNITS = [
    {"unit_name": "Box", "qty_in_base_units": 240, "price": 480.0},
    {"unit_name": "File", "qty_in_base_units": 20, "price": 45.0},
    {"unit_name": "Tablet", "qty_in_base_units": 1, "price": 2.5},
]


def _setup_medicine(app, stock_boxes=5):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)
        from inventory import add_stock
        add_stock(medicine_id, "Box", stock_boxes)
        return medicine_id


def test_create_sale_decrements_stock_and_computes_total(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [
            {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4},
            {"medicine_id": medicine_id, "unit_name": "File", "quantity": 1},
        ])
        assert result["total"] == pytest.approx(4 * 2.5 + 1 * 45.0)
        medicine = get_medicine(medicine_id)
        assert medicine["stock_in_base_units"] == 5 * 240 - 4 - 20


def test_create_sale_rejects_insufficient_stock(app):
    medicine_id = _setup_medicine(app, stock_boxes=1)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "Box", "quantity": 5},
            ])


def test_create_sale_rejects_unknown_unit(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        with pytest.raises(ValueError):
            create_sale(user_id, [
                {"medicine_id": medicine_id, "unit_name": "Pallet", "quantity": 1},
            ])


def test_void_sale_restores_stock(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [
            {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4},
        ])
        void_sale(result["sale_id"])
        medicine = get_medicine(medicine_id)
        assert medicine["stock_in_base_units"] == 5 * 240
        sale = get_sale(result["sale_id"])
        assert sale["sale"]["voided"] == 1


def test_void_sale_twice_raises(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        result = create_sale(user_id, [
            {"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1},
        ])
        void_sale(result["sale_id"])
        with pytest.raises(ValueError):
            void_sale(result["sale_id"])


def test_today_sales_total_excludes_voided(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "pw", "staff")
        r1 = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 4}])
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}])
        void_sale(r1["sale_id"])
        assert today_sales_total() == pytest.approx(2 * 2.5)


def test_sales_search_route_returns_matching_medicines(admin_client, app):
    _setup_medicine(app)
    response = admin_client.get("/sales/search?q=ceta")
    assert response.status_code == 200
    data = response.get_json()
    assert data[0]["name"] == "Cetamol"
    assert any(u["unit_name"] == "Tablet" for u in data[0]["units"])


def test_finalize_sale_route_creates_sale_and_returns_redirect(admin_client, app):
    medicine_id = _setup_medicine(app)
    response = admin_client.post(
        "/sales",
        json={"items": [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}]},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "sale_id" in data


def test_void_route_requires_admin(staff_client, app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("someone", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])
    response = staff_client.post(f"/sales/{result['sale_id']}/void")
    assert response.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sales.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sales'`

- [ ] **Step 3: Write sales.py**

```python
from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from auth import current_user, login_required, role_required
from db import get_db
from inventory import get_medicine_units, search_medicines

bp = Blueprint("sales", __name__, url_prefix="/sales")


def create_sale(user_id, items):
    if not items:
        raise ValueError("sale must include at least one item")

    db = get_db()
    prepared = []
    total = 0.0
    for item in items:
        medicine_id = item["medicine_id"]
        unit_name = item["unit_name"]
        quantity = item["quantity"]
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        unit_row = db.execute(
            "SELECT qty_in_base_units, price FROM medicine_units "
            "WHERE medicine_id = ? AND unit_name = ?",
            (medicine_id, unit_name),
        ).fetchone()
        if unit_row is None:
            raise ValueError(f"unknown unit '{unit_name}' for medicine {medicine_id}")

        medicine_row = db.execute(
            "SELECT stock_in_base_units FROM medicines WHERE id = ?", (medicine_id,)
        ).fetchone()
        if medicine_row is None:
            raise ValueError(f"medicine {medicine_id} not found")

        base_units_needed = unit_row["qty_in_base_units"] * quantity
        if medicine_row["stock_in_base_units"] < base_units_needed:
            raise ValueError(f"insufficient stock for medicine {medicine_id}")

        subtotal = round(unit_row["price"] * quantity, 2)
        total += subtotal
        prepared.append((medicine_id, unit_name, quantity, unit_row["price"], subtotal, base_units_needed))

    total = round(total, 2)
    cur = db.execute(
        "INSERT INTO sales (user_id, timestamp, total, voided) VALUES (?, datetime('now'), ?, 0)",
        (user_id, total),
    )
    sale_id = cur.lastrowid
    for medicine_id, unit_name, quantity, price, subtotal, base_units_needed in prepared:
        db.execute(
            "INSERT INTO sale_items (sale_id, medicine_id, unit_name, quantity, unit_price, subtotal) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sale_id, medicine_id, unit_name, quantity, price, subtotal),
        )
        db.execute(
            "UPDATE medicines SET stock_in_base_units = stock_in_base_units - ? WHERE id = ?",
            (base_units_needed, medicine_id),
        )
    db.commit()
    return {"sale_id": sale_id, "total": total}


def void_sale(sale_id):
    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if sale is None:
        raise ValueError(f"sale {sale_id} not found")
    if sale["voided"]:
        raise ValueError(f"sale {sale_id} already voided")

    items = db.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
    for item in items:
        unit_row = db.execute(
            "SELECT qty_in_base_units FROM medicine_units WHERE medicine_id = ? AND unit_name = ?",
            (item["medicine_id"], item["unit_name"]),
        ).fetchone()
        base_units = unit_row["qty_in_base_units"] * item["quantity"]
        db.execute(
            "UPDATE medicines SET stock_in_base_units = stock_in_base_units + ? WHERE id = ?",
            (base_units, item["medicine_id"]),
        )
    db.execute("UPDATE sales SET voided = 1 WHERE id = ?", (sale_id,))
    db.commit()


def today_sales_total():
    db = get_db()
    row = db.execute(
        "SELECT COALESCE(SUM(total), 0) AS total FROM sales "
        "WHERE voided = 0 AND date(timestamp) = date('now')"
    ).fetchone()
    return row["total"]


def get_sale(sale_id):
    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if sale is None:
        return None
    items = db.execute(
        "SELECT si.*, m.name AS medicine_name FROM sale_items si "
        "JOIN medicines m ON m.id = si.medicine_id WHERE si.sale_id = ?",
        (sale_id,),
    ).fetchall()
    return {"sale": sale, "items": items}


@bp.route("/new")
@login_required
def new_sale():
    return render_template("new_sale.html")


@bp.route("/search")
@login_required
def search():
    query = request.args.get("q", "")
    medicines = search_medicines(query)
    results = []
    for m in medicines:
        units = get_medicine_units(m["id"])
        results.append({
            "id": m["id"],
            "name": m["name"],
            "units": [{"unit_name": u["unit_name"], "price": u["price"]} for u in units],
        })
    return jsonify(results)


@bp.route("", methods=["POST"])
@login_required
def finalize():
    payload = request.get_json()
    user = current_user()
    try:
        result = create_sale(user["id"], payload["items"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@bp.route("/<int:sale_id>/receipt")
@login_required
def receipt(sale_id):
    sale = get_sale(sale_id)
    if sale is None:
        return "Sale not found", 404
    return render_template("receipt.html", sale=sale["sale"], items=sale["items"])


@bp.route("/<int:sale_id>/void", methods=["POST"])
@role_required("admin")
def void(sale_id):
    try:
        void_sale(sale_id)
    except ValueError as e:
        return str(e), 400
    return redirect(url_for("sales.receipt", sale_id=sale_id))
```

- [ ] **Step 4: Write templates/new_sale.html**

```html
{% extends "base.html" %}
{% block title %}New Sale{% endblock %}
{% block content %}
<h1>New Sale</h1>
<input type="text" id="search-box" placeholder="Search medicine by name...">
<ul id="search-results"></ul>

<h2>Current Bill</h2>
<table id="bill-table">
  <tr><th>Medicine</th><th>Unit</th><th>Qty</th><th>Price</th><th>Subtotal</th></tr>
</table>
<p>Total: <span id="bill-total">0.00</span></p>
<button type="button" id="finalize-btn">Finalize Sale</button>

<script>
var bill = [];

function render() {
  var table = document.getElementById("bill-table");
  table.innerHTML = "<tr><th>Medicine</th><th>Unit</th><th>Qty</th><th>Price</th><th>Subtotal</th></tr>";
  var total = 0;
  bill.forEach(function (item) {
    var subtotal = item.price * item.quantity;
    total += subtotal;
    var row = table.insertRow();
    row.innerHTML = "<td>" + item.name + "</td><td>" + item.unit_name + "</td><td>" +
      item.quantity + "</td><td>" + item.price.toFixed(2) + "</td><td>" + subtotal.toFixed(2) + "</td>";
  });
  document.getElementById("bill-total").textContent = total.toFixed(2);
}

document.getElementById("search-box").addEventListener("input", function (e) {
  var q = e.target.value;
  if (!q) { document.getElementById("search-results").innerHTML = ""; return; }
  fetch("/sales/search?q=" + encodeURIComponent(q))
    .then(function (r) { return r.json(); })
    .then(function (medicines) {
      var list = document.getElementById("search-results");
      list.innerHTML = "";
      medicines.forEach(function (m) {
        m.units.forEach(function (u) {
          var li = document.createElement("li");
          li.textContent = m.name + " - " + u.unit_name + " (" + u.price.toFixed(2) + ")";
          li.style.cursor = "pointer";
          li.addEventListener("click", function () {
            var quantity = parseInt(prompt("Quantity of " + u.unit_name + "?", "1"), 10);
            if (quantity > 0) {
              bill.push({ medicine_id: m.id, name: m.name, unit_name: u.unit_name, price: u.price, quantity: quantity });
              render();
            }
          });
          list.appendChild(li);
        });
      });
    });
});

document.getElementById("finalize-btn").addEventListener("click", function () {
  if (bill.length === 0) { return; }
  fetch("/sales", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items: bill.map(function (i) {
      return { medicine_id: i.medicine_id, unit_name: i.unit_name, quantity: i.quantity };
    }) }),
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.error) { alert(data.error); return; }
      window.location = "/sales/" + data.sale_id + "/receipt";
    });
});
</script>
{% endblock %}
```

- [ ] **Step 5: Write templates/receipt.html**

```html
{% extends "base.html" %}
{% block title %}Receipt #{{ sale['id'] }}{% endblock %}
{% block content %}
<h1>Receipt #{{ sale['id'] }}{% if sale['voided'] %} (VOIDED){% endif %}</h1>
<p>Date: {{ sale['timestamp'] }}</p>
<table>
  <tr><th>Medicine</th><th>Unit</th><th>Qty</th><th>Unit Price</th><th>Subtotal</th></tr>
  {% for item in items %}
  <tr>
    <td>{{ item['medicine_name'] }}</td>
    <td>{{ item['unit_name'] }}</td>
    <td>{{ item['quantity'] }}</td>
    <td>{{ "%.2f"|format(item['unit_price']) }}</td>
    <td>{{ "%.2f"|format(item['subtotal']) }}</td>
  </tr>
  {% endfor %}
</table>
<p><strong>Total: {{ "%.2f"|format(sale['total']) }}</strong></p>
<button class="no-print" onclick="window.print()">Print</button>
{% if session.get('role') == 'admin' and not sale['voided'] %}
<form method="post" action="{{ url_for('sales.void', sale_id=sale['id']) }}" class="no-print">
  <button type="submit">Void Sale</button>
</form>
{% endif %}
{% endblock %}
```

- [ ] **Step 6: Modify app.py — register sales blueprint**

```python
# add import near the top
import sales
```

```python
# inside create_app(), after app.register_blueprint(inventory.bp)
    app.register_blueprint(sales.bp)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_sales.py -v`
Expected: PASS (9 tests)

- [ ] **Step 8: Commit**

```bash
git add sales.py templates/new_sale.html templates/receipt.html app.py tests/test_sales.py
git commit -m "feat: add sales flow with multi-unit billing, printable receipt, and void"
```

---

### Task 5: Dashboard — low stock + today's sales

**Files:**
- Create: `dashboard.py`
- Create: `templates/dashboard.html`
- Modify: `app.py` (register `dashboard.bp`)
- Modify: `tests/test_auth.py` (re-add the login-redirect test now that `/` exists)
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `inventory.low_stock_medicines()`, `sales.today_sales_total()`, `auth.login_required`.
- Produces: route `dashboard.home` at `/`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard.py
from inventory import add_medicine, add_stock

TABLET_UNITS = [
    {"unit_name": "Box", "qty_in_base_units": 240, "price": 480.0},
    {"unit_name": "Tablet", "qty_in_base_units": 1, "price": 2.5},
]


def test_dashboard_shows_low_stock_and_todays_total(admin_client, app):
    with app.app_context():
        medicine_id = add_medicine("Cetamol", "Tablet", 100, TABLET_UNITS)
        add_stock(medicine_id, "Tablet", 10)  # below threshold of 100

    response = admin_client.get("/")
    assert response.status_code == 200
    assert b"Cetamol" in response.data
    assert b"0.00" in response.data  # no sales yet today


def test_dashboard_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard.py -v`
Expected: FAIL — 404 on `GET /` (no route registered yet)

- [ ] **Step 3: Write dashboard.py**

```python
from flask import Blueprint, render_template

from auth import login_required
from inventory import low_stock_medicines
from sales import today_sales_total

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def home():
    return render_template(
        "dashboard.html",
        low_stock=low_stock_medicines(),
        todays_total=today_sales_total(),
    )
```

- [ ] **Step 4: Write templates/dashboard.html**

```html
{% extends "base.html" %}
{% block title %}Dashboard{% endblock %}
{% block content %}
<h1>Dashboard</h1>
<p><a href="{{ url_for('inventory.list_medicines_view') }}">Medicines</a> |
   <a href="{{ url_for('sales.new_sale') }}">New Sale</a>
   {% if session.get('role') == 'admin' %}
   | <a href="{{ url_for('users.list_users') }}">Staff Accounts</a>
   {% endif %}
</p>

<h2>Today's Sales Total</h2>
<p>{{ "%.2f"|format(todays_total) }}</p>

<h2>Low Stock Medicines</h2>
{% if low_stock %}
<table>
  <tr><th>Name</th><th>Stock (base units)</th><th>Threshold</th></tr>
  {% for m in low_stock %}
  <tr class="low-stock">
    <td>{{ m['name'] }}</td>
    <td>{{ m['stock_in_base_units'] }}</td>
    <td>{{ m['low_stock_threshold'] }}</td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p>No medicines are low on stock.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Modify app.py — register dashboard blueprint**

```python
# add import near the top
import dashboard
```

```python
# inside create_app(), after app.register_blueprint(sales.bp)
    app.register_blueprint(dashboard.bp)
```

- [ ] **Step 6: Modify tests/test_auth.py — re-add the redirect test**

```python
# append to tests/test_auth.py
def test_dashboard_redirects_to_login_when_not_authenticated(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_dashboard.py tests/test_auth.py -v`
Expected: PASS (2 + 5 tests)

- [ ] **Step 8: Commit**

```bash
git add dashboard.py templates/dashboard.html app.py tests/test_dashboard.py tests/test_auth.py
git commit -m "feat: add dashboard with low-stock alert and today's sales total"
```

---

### Task 6: Staff account management (admin only)

**Files:**
- Create: `users.py`
- Create: `templates/users.html`
- Modify: `app.py` (register `users.bp`)
- Modify: `templates/base.html` (add "Staff Accounts" nav link for admins) — *(already added inline in dashboard.html; base.html nav stays minimal on purpose, see Step 4)*
- Test: `tests/test_users.py`

**Interfaces:**
- Consumes: `auth.create_user`, `auth.role_required`.
- Produces: `users.list_staff() -> list[Row]`, `users.delete_staff(user_id) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_users.py
import pytest

from auth import create_user
from users import delete_staff, list_staff


def test_list_staff_returns_only_staff_role(app):
    with app.app_context():
        create_user("admin", "pw", "admin")
        create_user("staff1", "pw", "staff")
        staff = list_staff()
        assert len(staff) == 1
        assert staff[0]["username"] == "staff1"


def test_delete_staff_removes_user(app):
    with app.app_context():
        user_id = create_user("staff1", "pw", "staff")
        delete_staff(user_id)
        assert list_staff() == []


def test_delete_staff_refuses_to_delete_admin(app):
    with app.app_context():
        admin_id = create_user("admin", "pw", "admin")
        with pytest.raises(ValueError):
            delete_staff(admin_id)


def test_users_route_requires_admin(staff_client):
    response = staff_client.get("/users")
    assert response.status_code == 403


def test_users_add_route_creates_staff(admin_client, app):
    response = admin_client.post("/users/add", data={"username": "newstaff", "password": "pw123"})
    assert response.status_code == 302
    with app.app_context():
        assert any(u["username"] == "newstaff" for u in list_staff())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_users.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'users'`

- [ ] **Step 3: Write users.py**

```python
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
```

- [ ] **Step 4: Write templates/users.html**

```html
{% extends "base.html" %}
{% block title %}Staff Accounts{% endblock %}
{% block content %}
<h1>Staff Accounts</h1>
<table>
  <tr><th>Username</th><th></th></tr>
  {% for s in staff %}
  <tr>
    <td>{{ s['username'] }}</td>
    <td>
      <form method="post" action="{{ url_for('users.delete_user', user_id=s['id']) }}" class="inline-form">
        <button type="submit">Remove</button>
      </form>
    </td>
  </tr>
  {% endfor %}
</table>

<h2>Add Staff Account</h2>
<form method="post" action="{{ url_for('users.add_user') }}">
  <label>Username <input type="text" name="username" required></label>
  <label>Password <input type="password" name="password" required></label>
  <button type="submit">Add</button>
</form>
{% endblock %}
```

- [ ] **Step 5: Modify app.py — register users blueprint**

```python
# add import near the top
import users
```

```python
# inside create_app(), after app.register_blueprint(dashboard.bp)
    app.register_blueprint(users.bp)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_users.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Commit**

```bash
git add users.py templates/users.html app.py tests/test_users.py
git commit -m "feat: add admin-only staff account management"
```

---

### Task 7: Photo upload via QR handoff

**Files:**
- Create: `photos.py`
- Create: `templates/upload_photo.html`
- Modify: `app.py` (register `photos.bp`)
- Modify: `templates/medicine_add.html` (add "Add Photo from Phone" button + polling JS)
- Modify: `inventory.py` (accept `photo_path` in `add_medicine`, add `set_medicine_photo`)
- Test: `tests/test_photos.py`

**Interfaces:**
- Consumes: `db.get_db()`.
- Produces: `photos.create_photo_token() -> dict` (`{"token": str, "expires_at": str}`), `photos.is_token_valid(token) -> bool`, `photos.save_photo(token, file_storage) -> str` (path), `photos.get_token_photo(token) -> str | None`. `inventory.set_medicine_photo(medicine_id, photo_path) -> None` (new function this task adds to `inventory.py`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_photos.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_photos.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'photos'`

- [ ] **Step 3: Write photos.py**

```python
import io
import os
import socket
import uuid
from datetime import datetime, timedelta

import qrcode
from flask import Blueprint, Response, current_app, jsonify, render_template, request

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
    filename = f"{token}{ext}"
    photos_dir = os.path.join(current_app.root_path, "static", "photos")
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
def qr_image(token):
    lan_ip = get_lan_ip()
    upload_url = f"http://{lan_ip}:{PORT}/photos/upload/{token}"
    img = qrcode.make(upload_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")


@bp.route("/upload/<token>", methods=["GET", "POST"])
def upload(token):
    if request.method == "POST":
        if not is_token_valid(token):
            return "This link has expired. Ask for a new QR code.", 400
        file_storage = request.files["photo"]
        save_photo(token, file_storage)
        return render_template("upload_photo.html", token=token, done=True)
    return render_template("upload_photo.html", token=token, done=False)


@bp.route("/status/<token>")
def status(token):
    photo_path = get_token_photo(token)
    return jsonify({"uploaded": photo_path is not None, "photo_path": photo_path})
```

- [ ] **Step 4: Write templates/upload_photo.html**

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Upload Medicine Photo</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  <main>
    {% if done %}
    <h1>Photo uploaded!</h1>
    <p>You can close this page now.</p>
    {% else %}
    <h1>Upload Medicine Photo</h1>
    <form method="post" enctype="multipart/form-data">
      <input type="file" name="photo" accept="image/*" capture="environment" required>
      <button type="submit">Upload</button>
    </form>
    {% endif %}
  </main>
</body>
</html>
```

- [ ] **Step 5: Modify inventory.py — add photo_path support**

```python
# change add_medicine's signature and INSERT to accept photo_path (default None)
def add_medicine(name, category, low_stock_threshold, units, photo_path=None):
    if not units:
        raise ValueError("medicine must have at least one unit")
    base_units = [u for u in units if u["qty_in_base_units"] == 1]
    if len(base_units) != 1:
        raise ValueError("medicine must have exactly one base unit (qty_in_base_units = 1)")

    db = get_db()
    cur = db.execute(
        "INSERT INTO medicines (name, category, photo_path, stock_in_base_units, low_stock_threshold) "
        "VALUES (?, ?, ?, 0, ?)",
        (name, category, photo_path, low_stock_threshold),
    )
    medicine_id = cur.lastrowid
    for u in units:
        db.execute(
            "INSERT INTO medicine_units (medicine_id, unit_name, qty_in_base_units, price) "
            "VALUES (?, ?, ?, ?)",
            (medicine_id, u["unit_name"], u["qty_in_base_units"], u["price"]),
        )
    db.commit()
    return medicine_id
```

```python
# add new function near the other medicine functions
def set_medicine_photo(medicine_id, photo_path):
    db = get_db()
    db.execute("UPDATE medicines SET photo_path = ? WHERE id = ?", (photo_path, medicine_id))
    db.commit()
```

```python
# in add_medicine_view(), read the optional token from the form and resolve its photo
from photos import get_token_photo

@bp.route("/add", methods=["GET", "POST"])
@role_required("admin")
def add_medicine_view():
    if request.method == "POST":
        unit_names = request.form.getlist("unit_name")
        unit_qtys = request.form.getlist("unit_qty")
        unit_prices = request.form.getlist("unit_price")
        units = [
            {"unit_name": n, "qty_in_base_units": int(q), "price": float(p)}
            for n, q, p in zip(unit_names, unit_qtys, unit_prices)
            if n.strip()
        ]
        photo_token = request.form.get("photo_token")
        photo_path = get_token_photo(photo_token) if photo_token else None
        add_medicine(
            request.form["name"],
            request.form["category"],
            int(request.form["low_stock_threshold"]),
            units,
            photo_path=photo_path,
        )
        return redirect(url_for("inventory.list_medicines_view"))
    return render_template("medicine_add.html")
```

- [ ] **Step 6: Modify templates/medicine_add.html — add photo-from-phone button + polling**

```html
<!-- add inside the <form>, after the low_stock_threshold field -->
<label>Photo (optional)
  <input type="hidden" name="photo_token" id="photo_token">
  <button type="button" id="request-photo-btn">Add Photo from Phone</button>
  <span id="photo-status"></span>
</label>
```

```html
<!-- add before the closing {% endblock %}, alongside the existing <script> -->
<script>
document.getElementById("request-photo-btn").addEventListener("click", function () {
  fetch("/photos/new-token", { method: "POST" })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      document.getElementById("photo_token").value = data.token;
      var status = document.getElementById("photo-status");
      status.innerHTML = '<img src="' + data.qr_url + '" alt="Scan with phone" width="150">' +
        '<br>Waiting for photo...';
      var poll = setInterval(function () {
        fetch("/photos/status/" + data.token)
          .then(function (r) { return r.json(); })
          .then(function (s) {
            if (s.uploaded) {
              clearInterval(poll);
              status.innerHTML = "Photo received!";
            }
          });
      }, 3000);
    });
});
</script>
```

- [ ] **Step 7: Modify app.py — register photos blueprint**

```python
# add import near the top
import photos
```

```python
# inside create_app(), after app.register_blueprint(users.bp)
    app.register_blueprint(photos.bp)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_photos.py -v`
Expected: PASS (6 tests)

- [ ] **Step 9: Run the full test suite to confirm nothing else broke**

Run: `pytest -v`
Expected: all tests PASS

- [ ] **Step 10: Commit**

```bash
git add photos.py templates/upload_photo.html templates/medicine_add.html inventory.py app.py tests/test_photos.py
git commit -m "feat: add QR-handoff photo upload from phone for medicines"
```

---

### Task 8: Launcher, docs, and end-to-end manual verification

**Files:**
- Create: `run.bat`
- Create: `README.md`
- Create: `static/photos/.gitkeep`

**Interfaces:** None — this task wires up deployment and manual verification, no new code interfaces.

- [ ] **Step 1: Write run.bat**

```bat
@echo off
cd /d %~dp0
start /min cmd /c "python app.py"
timeout /t 2 /nobreak >nul
start "" http://localhost:5000/
```

- [ ] **Step 2: Write static/photos/.gitkeep**

```
```

(empty file, keeps the `static/photos/` directory tracked by git even though actual uploaded photos are gitignored)

- [ ] **Step 3: Write README.md**

```markdown
# Pharmacy Inventory & Billing System

Local-only inventory and sales system. Runs on one computer, no internet required.

## First-time setup

1. Install Python 3.10+.
2. Open a terminal in this folder and run:
   ```
   pip install -r requirements.txt
   ```
3. Create the first admin account:
   ```
   flask --app app init-admin admin yourpassword
   ```

## Day-to-day use

Double-click `run.bat`. It starts the server and opens your browser to the app.

## Using it from a phone (same WiFi only, no internet needed)

1. Find this computer's local network address — Windows: open a terminal and run `ipconfig`, look for "IPv4 Address" (e.g. `192.168.1.5`).
2. On your phone, connect to the same WiFi as this computer.
3. Open a browser on the phone and go to `http://<that address>:5000`.

The "Add Photo from Phone" button on the Add Medicine page generates a QR code — scanning it with your phone opens a camera-upload page for that medicine's photo, no typing the address needed.

## Backing up your data

Everything is stored in a single file: `pharmacy.db`. Copy it somewhere safe periodically (e.g. a USB drive).
```

- [ ] **Step 4: Run the full automated test suite**

Run: `pytest -v`
Expected: all tests PASS

- [ ] **Step 5: Manual end-to-end verification**

Follow the setup steps in README.md, then walk through:
1. `pip install -r requirements.txt`, `flask --app app init-admin admin adminpass`, run `run.bat`.
2. Log in as admin. Add a tablet-style medicine (Box/File/Tablet units) and a liquid-style medicine (single unit) — confirm per-tablet price shows correctly on the medicines list only where relevant.
3. Add stock to both via "Add Stock" — confirm the stock number updates correctly with unit conversion.
4. Log out, log in as a staff account (create one via Staff Accounts first) — confirm price-editing/medicine-adding/void/user-management links and routes are unavailable (403 on direct URL access too).
5. As staff, make a sale mixing unit levels across two medicines — confirm the bill totals correctly, the receipt page shows correctly, and print preview looks reasonable.
6. Log back in as admin, void that sale — confirm stock is restored and the receipt shows "VOIDED".
7. Drop a medicine's stock below its threshold — confirm it shows on the dashboard low-stock list, and confirm today's sales total matches what was actually sold (minus the voided sale).
8. From a phone on the same WiFi, browse to the PC's LAN IP on port 5000 — confirm the app loads.
9. On the Add Medicine page, click "Add Photo from Phone", scan the QR with the phone, upload a photo — confirm the desktop page shows "Photo received!" without manually refreshing, and the medicine record ends up with that photo attached after saving the form.

- [ ] **Step 6: Commit**

```bash
git add run.bat README.md static/photos/.gitkeep
git commit -m "docs: add launcher script and setup/usage README"
```
