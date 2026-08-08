# Pharmacy System UX & Data Model Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bare-HTML v1 pharmacy app with a real visual design system, a category-driven packaging data model (no more freeform unit rows), a keyboard-first POS flow, seller attribution in sales history, and password management — all styled consistently, with every native browser dialog replaced by a custom modal.

**Architecture:** Same Flask blueprint structure as v1 (`auth`/`inventory`/`sales`/`dashboard`/`users`/`photos`), extended with: a `packaging_type` column driving `medicines`/`medicine_units` structure, an `is_sellable` flag on `medicine_units`, a shared CSS design system + reusable modal JS helper loaded via `base.html`, and one new route (`auth.change_password`) plus one new capability on the existing `users` blueprint (`reset_password`).

**Tech Stack:** Same as v1 — Flask, SQLite, Jinja2, vanilla JS, pytest. No new dependencies.

## Global Constraints

- No data migration path — this ships as a fresh `schema.sql`; the app has no real production data yet.
- Every native `alert()`/`confirm()`/`prompt()` in the codebase must be gone by the end of this plan — replaced by the shared modal component.
- Money values stay Python floats rounded to 2 decimals at every computation/input boundary (unchanged rule from v1).
- Stock stays in base units; the only sellable units for a `box_file` medicine are File and Tablet — Box is stock-intake-only (`is_sellable = 0`).
- Every page's `<h1>` gets a one-line description directly beneath it (via `base.html`'s `page_title`/`page_desc` blocks).
- Visual design tokens (colors, fonts, layout) come from the approved mockup — see Task 1 for the exact values. Do not invent new colors/fonts elsewhere in the plan.
- `add_medicine`'s signature is a breaking change from v1. Any task that touches a test file calling the old signature must fix it, not just its own new tests — the full suite must pass at the end of every task.

---

## File Structure (new/changed only)

```
pharmacy_management_system/
  schema.sql                    # medicines.category -> packaging_type; medicine_units gains is_sellable
  inventory.py                  # add_medicine rewritten; + sellable_units(), count_medicines()
  auth.py                       # + change_own_password(), change_password route
  users.py                      # + reset_staff_password(), reset_password route
  sales.py                      # search filtered to sellable units + photo/packaging_type; list_sales/get_sale gain seller username
  dashboard.py                  # + total_products in render context
  static/
    style.css                   # full design-system rewrite (replaces v1's bare CSS)
    js/
      modal.js                  # new — shared modal open/close/escape/backdrop-click helper
  templates/
    base.html                   # sidebar + topbar shell, page_title/page_desc blocks, modal script include
    login.html                  # auth-shell/auth-card styling
    change_password.html        # new
    medicine_add.html           # category-driven fields (rewritten)
    medicines.html              # restyled, packaging_type badge
    add_stock.html              # restyled
    dashboard.html              # stat cards + quick actions + low-stock table
    new_sale.html                # keyboard-first search + quantity modal (rewritten)
    sales_list.html             # + Sold By column, restyled
    receipt.html                # + Sold by line, void confirm modal, restyled
    users.html                  # + reset-password modal, remove-confirm modal, restyled
  tests/
    helpers.py                  # new — make_box_file_medicine()/make_bottled_medicine() shared test helpers
    test_inventory.py           # rewritten for new add_medicine signature
    test_sales.py, test_dashboard.py, test_users.py  # updated to use new helpers
    test_auth.py                # + change_password tests
```

---

### Task 1: Visual design system + app shell + change-own-password

**Files:**
- Create: `static/js/modal.js`
- Modify: `static/style.css` (full rewrite)
- Modify: `templates/base.html` (full rewrite)
- Modify: `templates/login.html`
- Create: `templates/change_password.html`
- Modify: `auth.py` (add `change_own_password()` + `/change-password` route)
- Test: `tests/test_auth.py` (append)

**Interfaces:**
- Produces: CSS custom properties (`--bg`, `--surface`, `--border`, `--text`, `--text-muted`, `--accent`, `--accent-soft`, `--good`/`--good-soft`, `--warning`/`--warning-soft`, `--critical`/`--critical-soft`) and component classes (`.card`, `.stat-card`, `.action-card`, `.badge`, `.btn`/`.btn-primary`/`.btn-secondary`/`.btn-danger`, `.field`, `.styled-form`, `.modal-backdrop`/`.modal`, `.search-box`, `.num`) that every later task's templates use — do not invent new ad-hoc classes without adding them here or appending to this file.
- Produces: `openModal(id)`, `closeModal(id)` (global JS functions from `modal.js`, loaded on every page via `base.html`).
- Produces: `base.html` blocks `title`, `page_title`, `page_desc`, `content` (used by every authenticated page), `auth_content` (used only by `login.html`), `scripts` (page-specific `<script>` block, loaded after `modal.js`).
- Produces: `auth.change_own_password(user_id, current_password, new_password) -> None` (raises `ValueError` on wrong current password or empty new password), route `auth.change_password`.
- Consumes: existing `auth.login_required`, `db.get_db()`.

Note: existing templates (`dashboard.html`, `medicines.html`, `add_stock.html`, `new_sale.html`, `receipt.html`, `sales_list.html`, `users.html`) still use the v1 `base.html` structure (`{% block title %}` + their own inline `<h1>`) until their own tasks (2–7) rewrite them. Between this task and those, those pages will render with an empty topbar heading plus their own old inline heading — expected and harmless; existing tests check response text/status, not exact heading markup.

- [ ] **Step 1: Write static/js/modal.js**

```javascript
function openModal(id) {
  var el = document.getElementById(id);
  if (el) { el.classList.add("open"); }
}

function closeModal(id) {
  var el = document.getElementById(id);
  if (el) { el.classList.remove("open"); }
}

document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") {
    document.querySelectorAll(".modal-backdrop.open").forEach(function (m) {
      m.classList.remove("open");
    });
  }
});

document.addEventListener("click", function (e) {
  if (e.target.classList.contains("modal-backdrop")) {
    e.target.classList.remove("open");
  }
});
```

- [ ] **Step 2: Write static/style.css**

```css
:root {
  --bg: #f4f6f3; --surface: #ffffff; --border: #e1e6e0;
  --text: #191d1a; --text-muted: #64716a;
  --accent: #1f6f54; --accent-soft: #e1efe7;
  --good: #2e7d4f; --good-soft: #e5f3ea;
  --warning: #a8710b; --warning-soft: #fbf0dd;
  --critical: #b3261e; --critical-soft: #fbe9e7;
  --radius: 10px;
  --shadow: 0 1px 2px rgba(20,30,25,.04), 0 8px 24px -12px rgba(20,30,25,.10);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #12151a; --surface: #1a1e23; --border: #2a2f34;
    --text: #ecefe9; --text-muted: #98a29a;
    --accent: #4fae85; --accent-soft: #1c332a;
    --good: #4fae85; --good-soft: #1c332a;
    --warning: #dba53c; --warning-soft: #332b18;
    --critical: #e5665e; --critical-soft: #3a2220;
    --shadow: 0 1px 2px rgba(0,0,0,.3), 0 8px 24px -12px rgba(0,0,0,.5);
  }
}

* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font-family:"Segoe UI",-apple-system,"Helvetica Neue",Arial,sans-serif; font-size:14px; line-height:1.45; }
a { color: var(--accent); }
.app { display:grid; grid-template-columns:236px 1fr; min-height:100vh; }

.sidebar { background:var(--surface); border-right:1px solid var(--border); padding:20px 14px; display:flex; flex-direction:column; gap:4px; }
.brand { display:flex; align-items:center; gap:10px; padding:4px 10px 20px; font-weight:700; font-size:15px; }
.brand .mark { width:26px; height:26px; border-radius:7px; background:var(--accent); color:#fff; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; }
.nav-label { font-size:10.5px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--text-muted); padding:14px 12px 6px; }
.nav-item { display:flex; align-items:center; gap:10px; padding:9px 12px; border-radius:8px; color:var(--text); text-decoration:none; font-weight:500; font-size:13.5px; width:100%; background:none; border:none; cursor:pointer; text-align:left; font-family:inherit; }
.nav-item .icon { width:18px; height:18px; flex:none; opacity:.75; }
.nav-item.active { background:var(--accent-soft); color:var(--accent); font-weight:600; }
.nav-item.active .icon { opacity:1; }
.nav-item:not(.active):hover { background:var(--bg); }
.sidebar-bottom { margin-top:auto; }
.logout-btn { color: var(--critical); }

.main { padding:22px 28px 40px; }
.topbar { display:flex; align-items:flex-start; justify-content:space-between; margin-bottom:22px; gap:20px; }
.topbar h1 { margin:0 0 4px; font-size:21px; font-weight:700; letter-spacing:-.01em; }
.page-desc { margin:0; color:var(--text-muted); font-size:13px; max-width:60ch; }
.who { display:flex; align-items:center; gap:10px; font-size:13px; color:var(--text-muted); white-space:nowrap; }
.avatar { width:32px; height:32px; border-radius:50%; background:var(--accent-soft); color:var(--accent); display:flex; align-items:center; justify-content:center; font-weight:700; font-size:13px; }

.auth-shell { min-height:100vh; display:flex; align-items:center; justify-content:center; background:var(--bg); padding:20px; }
.auth-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow); padding:32px; width:100%; max-width:360px; }
.auth-card .brand { padding:0 0 20px; }
.auth-card h1 { font-size:19px; margin:0 0 4px; }

.card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow); }
.stat-row { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin-bottom:14px; }
.stat-card { padding:16px 18px; }
.stat-card .label { font-size:12.5px; color:var(--text-muted); font-weight:600; margin-bottom:8px; }
.stat-card .value { font-family:ui-monospace,"Cascadia Code","SFMono-Regular",Consolas,monospace; font-variant-numeric:tabular-nums; font-size:26px; font-weight:700; letter-spacing:-.01em; }
.stat-card .sub { font-size:12px; color:var(--text-muted); margin-top:6px; }
.stat-card.alert { background:var(--warning-soft); border-color:transparent; }
.stat-card.alert .label, .stat-card.alert .value, .stat-card.alert .sub { color:var(--warning); }

.action-row { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:24px; }
.action-card { padding:16px; display:flex; flex-direction:column; gap:8px; text-decoration:none; color:var(--text); transition:border-color .15s ease; }
.action-card:hover { border-color:var(--accent); }
.action-card .icon-badge { width:32px; height:32px; border-radius:8px; background:var(--accent-soft); display:flex; align-items:center; justify-content:center; }
.action-card .icon-badge svg { width:17px; height:17px; stroke:var(--accent); }
.action-card .title { font-weight:700; font-size:14.5px; }
.action-card .desc { font-size:12.5px; color:var(--text-muted); }
.action-card .go { font-size:12px; color:var(--accent); font-weight:600; margin-top:2px; }

.panel { padding:18px; margin-bottom:20px; }
.panel-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; gap:12px; flex-wrap:wrap; }
.panel-head h2 { font-size:15.5px; margin:0 0 3px; }
.panel-desc { font-size:12.5px; color:var(--text-muted); margin:0; }

.search-box { display:flex; align-items:center; gap:8px; border:1px solid var(--border); border-radius:8px; padding:7px 10px; color:var(--text-muted); font-size:13px; background:var(--surface); }
.search-box input { border:none; outline:none; background:none; color:var(--text); font-size:13px; width:100%; font-family:inherit; }
.search-box svg { width:14px; height:14px; stroke:var(--text-muted); flex:none; }
.search-results { margin-top:10px; max-height:280px; overflow-y:auto; display:flex; flex-direction:column; gap:2px; }
.search-result { display:flex; align-items:center; gap:10px; padding:8px 10px; border-radius:8px; cursor:pointer; }
.search-result.highlighted, .search-result:hover { background:var(--accent-soft); }

.table-scroll { overflow-x:auto; }
table { width:100%; border-collapse:collapse; }
th { text-align:left; font-size:11.5px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; color:var(--text-muted); padding:10px 12px; border-bottom:1px solid var(--border); }
td { padding:11px 12px; border-bottom:1px solid var(--border); font-size:13.5px; vertical-align:middle; }
tr:last-child td { border-bottom:none; }
.num { font-family:ui-monospace,"Cascadia Code","SFMono-Regular",Consolas,monospace; font-variant-numeric:tabular-nums; }
.med-cell { display:flex; align-items:center; gap:10px; }
.thumb { width:34px; height:34px; border-radius:8px; background:var(--accent-soft); display:flex; align-items:center; justify-content:center; flex:none; overflow:hidden; }
.thumb img { width:100%; height:100%; object-fit:cover; }
.thumb svg { width:16px; height:16px; stroke:var(--accent); }
.med-name { font-weight:600; }
.med-sub { font-size:12px; color:var(--text-muted); }

.badge { display:inline-flex; align-items:center; gap:5px; padding:3px 9px; border-radius:100px; font-size:11.5px; font-weight:700; }
.badge.good { background:var(--good-soft); color:var(--good); }
.badge.warn { background:var(--warning-soft); color:var(--warning); }
.badge.critical { background:var(--critical-soft); color:var(--critical); }
.badge::before { content:""; width:6px; height:6px; border-radius:50%; background:currentColor; }

form.styled-form { display:flex; flex-direction:column; gap:14px; max-width:480px; }
.field { display:flex; flex-direction:column; gap:5px; }
.field label { font-size:12.5px; font-weight:600; color:var(--text-muted); }
.field input, .field select { padding:9px 11px; border:1px solid var(--border); border-radius:8px; font-size:13.5px; background:var(--surface); color:var(--text); font-family:inherit; }
.field input:focus, .field select:focus { outline:2px solid var(--accent); outline-offset:1px; border-color:var(--accent); }
.field-hint { font-size:11.5px; color:var(--text-muted); }
.field-row { display:flex; gap:12px; }
.field-row .field { flex:1; }
.form-preview { font-size:12.5px; color:var(--accent); background:var(--accent-soft); padding:8px 11px; border-radius:8px; }

.btn { display:inline-flex; align-items:center; justify-content:center; gap:6px; padding:9px 16px; border-radius:8px; font-size:13.5px; font-weight:600; cursor:pointer; border:1px solid transparent; font-family:inherit; text-decoration:none; }
.btn-primary { background:var(--accent); color:#fff; }
.btn-primary:hover { opacity:.92; }
.btn-secondary { background:var(--surface); color:var(--text); border-color:var(--border); }
.btn-secondary:hover { background:var(--bg); }
.btn-danger { background:var(--critical); color:#fff; }
.btn-danger:hover { opacity:.92; }
.btn-block { width:100%; }
.btn-icon { padding:6px 9px; }

.flash { background:var(--warning-soft); color:var(--warning); border-radius:8px; padding:10px 14px; font-size:13px; margin-bottom:16px; }

.modal-backdrop { position:fixed; inset:0; background:rgba(10,14,12,.45); display:none; align-items:center; justify-content:center; z-index:100; padding:20px; }
.modal-backdrop.open { display:flex; }
.modal { background:var(--surface); border-radius:var(--radius); box-shadow:var(--shadow); padding:22px; width:100%; max-width:380px; }
.modal h3 { margin:0 0 6px; font-size:16px; }
.modal p { margin:0 0 16px; font-size:13.5px; color:var(--text-muted); }
.modal-actions { display:flex; justify-content:flex-end; gap:10px; margin-top:18px; }
.banner-error { background:var(--critical-soft); color:var(--critical); border-radius:8px; padding:8px 11px; font-size:12.5px; margin-bottom:12px; }

.unit-toggle { display:flex; gap:8px; flex-wrap:wrap; }
.unit-toggle button.selected { background:var(--accent); color:#fff; border-color:var(--accent); }
.kbd { font-family:ui-monospace,monospace; background:var(--bg); border:1px solid var(--border); border-radius:4px; padding:1px 6px; font-size:11.5px; }
.bill-total-row { text-align:right; font-weight:700; font-size:15px; padding:10px 0; }

@media print {
  .sidebar, .topbar .who, .no-print { display:none; }
  .app { grid-template-columns:1fr; }
}
```

- [ ] **Step 3: Write templates/base.html**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Pharmacy{% endblock %} — Shreekunj Pharmacy</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  {% if session.get('user_id') %}
  <div class="app">
    <aside class="sidebar">
      <div class="brand"><span class="mark">P</span> Shreekunj Pharmacy</div>
      <div class="nav-label">Menu</div>
      <a class="nav-item {{ 'active' if request.endpoint == 'dashboard.home' }}" href="{{ url_for('dashboard.home') }}">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="9" rx="1.5"></rect><rect x="14" y="3" width="7" height="5" rx="1.5"></rect><rect x="14" y="12" width="7" height="9" rx="1.5"></rect><rect x="3" y="16" width="7" height="5" rx="1.5"></rect></svg>
        Dashboard
      </a>
      <a class="nav-item {{ 'active' if request.endpoint == 'sales.new_sale' }}" href="{{ url_for('sales.new_sale') }}">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="14" rx="2"></rect><path d="M16 6V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"></path><path d="M2 11h20"></path></svg>
        POS
      </a>
      <a class="nav-item {{ 'active' if request.endpoint == 'inventory.list_medicines_view' }}" href="{{ url_for('inventory.list_medicines_view') }}">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v3"></path><path d="M3 8h18v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"></path></svg>
        Products
      </a>
      <a class="nav-item {{ 'active' if request.endpoint == 'sales.list_sales_view' }}" href="{{ url_for('sales.list_sales_view') }}">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"></path><path d="M14 2v6h6"></path></svg>
        Sales History
      </a>
      {% if session.get('role') == 'admin' %}
      <a class="nav-item {{ 'active' if request.endpoint and request.endpoint.startswith('users.') }}" href="{{ url_for('users.list_users') }}">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle></svg>
        Staff Accounts
      </a>
      {% endif %}
      <div class="sidebar-bottom">
        <div class="nav-label">Settings</div>
        <a class="nav-item {{ 'active' if request.endpoint == 'auth.change_password' }}" href="{{ url_for('auth.change_password') }}">
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20a8 8 0 1 0-8-8"></path><path d="M12 12v-4"></path><path d="M12 12l3 2"></path></svg>
          Change Password
        </a>
        <form method="post" action="{{ url_for('auth.logout') }}">
          <button type="submit" class="nav-item logout-btn">
            <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><path d="M16 17l5-5-5-5"></path><path d="M21 12H9"></path></svg>
            Log Out
          </button>
        </form>
      </div>
    </aside>
    <main class="main">
      <div class="topbar">
        <div>
          <h1>{% block page_title %}{% endblock %}</h1>
          <p class="page-desc">{% block page_desc %}{% endblock %}</p>
        </div>
        <div class="who"><span class="avatar">{{ session.get('username', '?')[:2]|upper }}</span> {{ session.get('username') }} · {{ session.get('role')|capitalize }}</div>
      </div>
      {% for message in get_flashed_messages() %}
        <div class="flash">{{ message }}</div>
      {% endfor %}
      {% block content %}{% endblock %}
    </main>
  </div>
  {% else %}
  <div class="auth-shell">
    {% for message in get_flashed_messages() %}
      <div class="flash">{{ message }}</div>
    {% endfor %}
    {% block auth_content %}{% endblock %}
  </div>
  {% endif %}
  <script src="{{ url_for('static', filename='js/modal.js') }}"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 4: Write templates/login.html**

```html
{% extends "base.html" %}
{% block title %}Login{% endblock %}
{% block auth_content %}
<div class="auth-card">
  <div class="brand"><span class="mark">P</span> Shreekunj Pharmacy</div>
  <h1>Sign in</h1>
  <p class="page-desc">Enter your username and password to access the system.</p>
  <form method="post" class="styled-form">
    <div class="field">
      <label>Username</label>
      <input type="text" name="username" required autofocus>
    </div>
    <div class="field">
      <label>Password</label>
      <input type="password" name="password" required>
    </div>
    <button type="submit" class="btn btn-primary btn-block">Log In</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 5: Write the failing test**

```python
# append to tests/test_auth.py
from auth import change_own_password


def test_change_own_password_succeeds_with_correct_current_password(app):
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "oldpass", "staff")
        change_own_password(user_id, "oldpass", "newpass123")
        from auth import verify_login
        assert verify_login("staff1", "newpass123") is not None
        assert verify_login("staff1", "oldpass") is None


def test_change_own_password_rejects_wrong_current_password(app):
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff1", "oldpass", "staff")
        with pytest.raises(ValueError):
            change_own_password(user_id, "wrongpass", "newpass123")


def test_change_password_route_requires_login(client):
    response = client.get("/change-password")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_change_password_route_updates_password(staff_client):
    response = staff_client.post("/change-password", data={
        "current_password": "staffpass",
        "new_password": "newstaffpass123",
    })
    assert response.status_code == 302
```

Add `import pytest` at the top of `tests/test_auth.py` if not already present.

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL — `ImportError: cannot import name 'change_own_password'`

- [ ] **Step 7: Modify auth.py — add change_own_password and route**

```python
# add near the other business-logic functions in auth.py
def change_own_password(user_id, current_password, new_password):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], current_password):
        raise ValueError("current password is incorrect")
    if not new_password:
        raise ValueError("new password cannot be empty")
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), user_id),
    )
    db.commit()
```

```python
# add near the other routes in auth.py, after logout()
@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        try:
            change_own_password(
                session["user_id"],
                request.form["current_password"],
                request.form["new_password"],
            )
            flash("Password updated.")
            return redirect(url_for("auth.change_password"))
        except ValueError as e:
            flash(str(e))
        except KeyError:
            flash("Invalid form input")
    return render_template("change_password.html")
```

- [ ] **Step 8: Write templates/change_password.html**

```html
{% extends "base.html" %}
{% block page_title %}Change Password{% endblock %}
{% block page_desc %}Update your own login password.{% endblock %}
{% block content %}
<div class="card panel">
  <form method="post" class="styled-form">
    <div class="field">
      <label>Current password</label>
      <input type="password" name="current_password" required autofocus>
    </div>
    <div class="field">
      <label>New password</label>
      <input type="password" name="new_password" required minlength="6">
    </div>
    <button type="submit" class="btn btn-primary">Update Password</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 9: Run the full test suite to confirm it passes with no regressions**

Run: `pytest -v`
Expected: all tests PASS (the new tests plus every existing v1 test — the app-shell change is additive and every existing endpoint/test targets response text or status codes, not exact markup)

- [ ] **Step 10: Commit**

```bash
git add static/js/modal.js static/style.css templates/base.html templates/login.html templates/change_password.html auth.py tests/test_auth.py
git commit -m "feat: add design system, app shell, and change-own-password"
```

---

### Task 2: Category-driven packaging data model + Add Medicine form

**Files:**
- Modify: `schema.sql`
- Modify: `inventory.py` (rewrite `add_medicine`, add `sellable_units()`, `count_medicines()`, rewrite `add_medicine_view`)
- Modify: `templates/medicine_add.html` (full rewrite)
- Create: `tests/helpers.py`
- Modify: `tests/test_inventory.py` (full rewrite)
- Modify: `tests/test_sales.py`, `tests/test_dashboard.py`, `tests/test_users.py` (replace old `add_medicine(...)` calls with the new helpers — full-suite compatibility, not just this task's own tests)

**Interfaces:**
- Consumes: `db.get_db()`, `auth.role_required`, `photos.get_token_photo`.
- Produces: `inventory.add_medicine(name, packaging_type, low_stock_threshold, photo_path=None, tablets_per_file=None, files_per_box=None, price_per_box=None, price_per_file=None, price_per_tablet=None, unit_name=None, unit_price=None) -> int` — all params after `low_stock_threshold` are optional and meant to be passed by keyword (nothing enforces that syntactically, but every call site in this plan does). `packaging_type` must be `"box_file"` (requires `tablets_per_file`/`files_per_box`/`price_per_box`/`price_per_file`/`price_per_tablet`) or `"bottled_other"` (requires `unit_name`/`unit_price`); anything else raises `ValueError`.
- Produces: `inventory.sellable_units(medicine_id) -> list[Row]` (only rows with `is_sellable = 1`, ordered smallest-first).
- Produces: `inventory.count_medicines() -> int`.
- Unchanged (still used as-is by later tasks): `get_medicine`, `get_medicine_units`, `search_medicines`, `add_stock`, `low_stock_medicines`, `unit_price_breakdown`, `set_medicine_photo`.
- Produces: `tests/helpers.make_box_file_medicine(name="Cetamol", low_stock_threshold=50, tablets_per_file=20, files_per_box=12, price_per_box=480.0, price_per_file=45.0, price_per_tablet=2.5) -> int` and `tests/helpers.make_bottled_medicine(name="Cough Syrup", low_stock_threshold=5, unit_name="Bottle", unit_price=120.0) -> int` — every later task's tests that need a medicine use these instead of hand-building units.

- [ ] **Step 1: Write tests/helpers.py**

```python
from inventory import add_medicine


def make_box_file_medicine(name="Cetamol", low_stock_threshold=50, tablets_per_file=20, files_per_box=12,
                            price_per_box=480.0, price_per_file=45.0, price_per_tablet=2.5):
    return add_medicine(
        name, "box_file", low_stock_threshold,
        tablets_per_file=tablets_per_file, files_per_box=files_per_box,
        price_per_box=price_per_box, price_per_file=price_per_file, price_per_tablet=price_per_tablet,
    )


def make_bottled_medicine(name="Cough Syrup", low_stock_threshold=5, unit_name="Bottle", unit_price=120.0):
    return add_medicine(name, "bottled_other", low_stock_threshold, unit_name=unit_name, unit_price=unit_price)
```

- [ ] **Step 2: Rewrite tests/test_inventory.py (the failing test for this task)**

```python
import pytest

from inventory import (
    add_medicine,
    add_stock,
    count_medicines,
    get_medicine_units,
    list_medicines,
    low_stock_medicines,
    search_medicines,
    sellable_units,
    unit_price_breakdown,
)
from helpers import make_bottled_medicine, make_box_file_medicine


def test_add_medicine_box_file_creates_three_units(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        units = get_medicine_units(medicine_id)
        assert [u["unit_name"] for u in units] == ["Tablet", "File", "Box"]
        by_name = {u["unit_name"]: u for u in units}
        assert by_name["Box"]["qty_in_base_units"] == 240
        assert by_name["File"]["qty_in_base_units"] == 20
        assert by_name["Tablet"]["qty_in_base_units"] == 1


def test_add_medicine_box_file_box_is_not_sellable(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        sellable = {u["unit_name"] for u in sellable_units(medicine_id)}
        assert sellable == {"File", "Tablet"}


def test_add_medicine_bottled_other_creates_one_sellable_unit(app):
    with app.app_context():
        medicine_id = make_bottled_medicine()
        units = get_medicine_units(medicine_id)
        assert len(units) == 1
        assert units[0]["unit_name"] == "Bottle"
        sellable = sellable_units(medicine_id)
        assert len(sellable) == 1
        assert sellable[0]["unit_name"] == "Bottle"


def test_add_medicine_rejects_invalid_packaging_type(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "not_a_type", 10)


def test_add_medicine_box_file_rejects_non_positive_conversion_numbers(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "box_file", 10, tablets_per_file=0, files_per_box=12,
                          price_per_box=1.0, price_per_file=1.0, price_per_tablet=1.0)


def test_add_medicine_bottled_other_requires_unit_name(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "bottled_other", 10, unit_name="", unit_price=10.0)


def test_add_medicine_bottled_other_rejects_negative_price(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_medicine("Bad Medicine", "bottled_other", 10, unit_name="Bottle", unit_price=-5.0)


def test_add_stock_converts_to_base_units(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        new_total = add_stock(medicine_id, "Box", 2)
        assert new_total == 480


def test_add_stock_unknown_unit_raises(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Pallet", 1)


def test_add_stock_rejects_fractional_quantity(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        with pytest.raises(ValueError):
            add_stock(medicine_id, "Box", 2.5)


def test_low_stock_medicines_flags_below_threshold(app):
    with app.app_context():
        medicine_id = make_box_file_medicine(low_stock_threshold=50)
        add_stock(medicine_id, "Tablet", 10)
        low = low_stock_medicines()
        assert any(m["id"] == medicine_id for m in low)


def test_unit_price_breakdown_computes_price_per_base_unit(app):
    with app.app_context():
        medicine_id = make_box_file_medicine()
        breakdown = unit_price_breakdown(medicine_id)
        by_unit = {b["unit_name"]: b for b in breakdown}
        assert by_unit["Box"]["price_per_base_unit"] == 2.0
        assert by_unit["Tablet"]["price_per_base_unit"] == 2.5


def test_search_medicines_matches_by_name(app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
        make_box_file_medicine(name="Napa Extra")
        results = search_medicines("ceta")
        assert len(results) == 1
        assert results[0]["name"] == "Cetamol"


def test_list_medicines_returns_all(app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
        make_bottled_medicine(name="Cough Syrup")
        assert len(list_medicines()) == 2


def test_count_medicines(app):
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
        make_bottled_medicine(name="Cough Syrup")
        assert count_medicines() == 2


def test_add_medicine_view_box_file_creates_medicine(admin_client, app):
    resp = admin_client.post("/medicines/add", data={
        "name": "Cetamol",
        "packaging_type": "box_file",
        "tablets_per_file": "20",
        "files_per_box": "12",
        "price_per_box": "480",
        "price_per_file": "45",
        "price_per_tablet": "2.5",
        "low_stock_threshold": "50",
    })
    assert resp.status_code == 302
    with app.app_context():
        assert len(list_medicines()) == 1


def test_add_medicine_view_bottled_other_creates_medicine(admin_client, app):
    resp = admin_client.post("/medicines/add", data={
        "name": "Cough Syrup",
        "packaging_type": "bottled_other",
        "unit_type": "Bottle",
        "unit_price": "120",
        "low_stock_threshold": "5",
    })
    assert resp.status_code == 302
    with app.app_context():
        assert len(list_medicines()) == 1


def test_add_medicine_view_invalid_input_flashes_error_not_500(admin_client):
    resp = admin_client.post("/medicines/add", data={
        "name": "Bad",
        "packaging_type": "box_file",
        "tablets_per_file": "not_a_number",
        "files_per_box": "12",
        "price_per_box": "480",
        "price_per_file": "45",
        "price_per_tablet": "2.5",
        "low_stock_threshold": "50",
    })
    assert resp.status_code == 200
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_inventory.py -v`
Expected: FAIL — old `add_medicine` signature doesn't accept the new keyword arguments (`TypeError`)

- [ ] **Step 4: Modify schema.sql**

```sql
-- replace the medicines and medicine_units table definitions with:
CREATE TABLE medicines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    packaging_type TEXT NOT NULL CHECK(packaging_type IN ('box_file', 'bottled_other')),
    photo_path TEXT,
    stock_in_base_units INTEGER NOT NULL DEFAULT 0,
    low_stock_threshold INTEGER NOT NULL DEFAULT 10
);

CREATE TABLE medicine_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    unit_name TEXT NOT NULL,
    qty_in_base_units INTEGER NOT NULL,
    price REAL NOT NULL,
    is_sellable INTEGER NOT NULL DEFAULT 1,
    UNIQUE(medicine_id, unit_name)
);
```

(`users`, `sales`, `sale_items`, `photo_tokens` tables are unchanged — leave them exactly as they are.)

- [ ] **Step 5: Rewrite inventory.py's add_medicine, and add sellable_units/count_medicines**

```python
# replace the existing add_medicine function entirely with:
def add_medicine(name, packaging_type, low_stock_threshold, photo_path=None,
                  tablets_per_file=None, files_per_box=None,
                  price_per_box=None, price_per_file=None, price_per_tablet=None,
                  unit_name=None, unit_price=None):
    def _positive_int(value):
        return isinstance(value, int) and not isinstance(value, bool) and value >= 1

    def _non_negative_price(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0

    if packaging_type == "box_file":
        if not (_positive_int(tablets_per_file) and _positive_int(files_per_box)):
            raise ValueError("tablets per file and files per box must be positive whole numbers")
        if not all(_non_negative_price(p) for p in (price_per_box, price_per_file, price_per_tablet)):
            raise ValueError("box, file, and tablet prices must all be set and non-negative")
        units = [
            {"unit_name": "Box", "qty_in_base_units": files_per_box * tablets_per_file,
             "price": round(price_per_box, 2), "is_sellable": 0},
            {"unit_name": "File", "qty_in_base_units": tablets_per_file,
             "price": round(price_per_file, 2), "is_sellable": 1},
            {"unit_name": "Tablet", "qty_in_base_units": 1,
             "price": round(price_per_tablet, 2), "is_sellable": 1},
        ]
    elif packaging_type == "bottled_other":
        if not unit_name or not unit_name.strip():
            raise ValueError("unit name is required")
        if not _non_negative_price(unit_price):
            raise ValueError("unit price must be a non-negative number")
        units = [
            {"unit_name": unit_name.strip(), "qty_in_base_units": 1,
             "price": round(unit_price, 2), "is_sellable": 1},
        ]
    else:
        raise ValueError("packaging_type must be 'box_file' or 'bottled_other'")

    db = get_db()
    cur = db.execute(
        "INSERT INTO medicines (name, packaging_type, photo_path, stock_in_base_units, low_stock_threshold) "
        "VALUES (?, ?, ?, 0, ?)",
        (name, packaging_type, photo_path, low_stock_threshold),
    )
    medicine_id = cur.lastrowid
    for u in units:
        db.execute(
            "INSERT INTO medicine_units (medicine_id, unit_name, qty_in_base_units, price, is_sellable) "
            "VALUES (?, ?, ?, ?, ?)",
            (medicine_id, u["unit_name"], u["qty_in_base_units"], u["price"], u["is_sellable"]),
        )
    db.commit()
    return medicine_id
```

```python
# add near get_medicine_units
def sellable_units(medicine_id):
    db = get_db()
    return db.execute(
        "SELECT * FROM medicine_units WHERE medicine_id = ? AND is_sellable = 1 ORDER BY qty_in_base_units ASC",
        (medicine_id,),
    ).fetchall()


def count_medicines():
    db = get_db()
    return db.execute("SELECT COUNT(*) AS c FROM medicines").fetchone()["c"]
```

```python
# replace the existing add_medicine_view function entirely with:
@bp.route("/add", methods=["GET", "POST"])
@role_required("admin")
def add_medicine_view():
    if request.method == "POST":
        try:
            packaging_type = request.form["packaging_type"]
            photo_token = request.form.get("photo_token")
            photo_path = get_token_photo(photo_token) if photo_token else None
            kwargs = {}
            if packaging_type == "box_file":
                kwargs = {
                    "tablets_per_file": int(request.form["tablets_per_file"]),
                    "files_per_box": int(request.form["files_per_box"]),
                    "price_per_box": round(float(request.form["price_per_box"]), 2),
                    "price_per_file": round(float(request.form["price_per_file"]), 2),
                    "price_per_tablet": round(float(request.form["price_per_tablet"]), 2),
                }
            elif packaging_type == "bottled_other":
                unit_name = request.form.get("unit_type", "")
                if unit_name == "Other":
                    unit_name = request.form.get("custom_unit_name", "").strip()
                kwargs = {
                    "unit_name": unit_name,
                    "unit_price": round(float(request.form["unit_price"]), 2),
                }
            else:
                raise ValueError("invalid category selected")
            add_medicine(
                request.form["name"],
                packaging_type,
                int(request.form["low_stock_threshold"]),
                photo_path=photo_path,
                **kwargs,
            )
            return redirect(url_for("inventory.list_medicines_view"))
        except ValueError as e:
            flash(str(e))
        except (KeyError, TypeError):
            flash("Invalid form input")
    return render_template("medicine_add.html")
```

Leave every other function in `inventory.py` (`set_medicine_photo`, `list_medicines`, `get_medicine`, `get_medicine_units`, `search_medicines`, `add_stock`, `add_stock_view`, `low_stock_medicines`, `unit_price_breakdown`, `list_medicines_view`) exactly as they are.

- [ ] **Step 6: Rewrite templates/medicine_add.html**

```html
{% extends "base.html" %}
{% block page_title %}Add Medicine{% endblock %}
{% block page_desc %}Add a new medicine to the catalog and set its packaging and pricing.{% endblock %}
{% block content %}
<div class="card panel" style="max-width:520px">
  <form method="post" class="styled-form" id="add-medicine-form">
    <div class="field">
      <label>Name</label>
      <input type="text" name="name" required autofocus>
    </div>
    <div class="field">
      <label>Category</label>
      <select name="packaging_type" id="packaging-type">
        <option value="box_file">Box/File (tablets, capsules — sold by file or tablet)</option>
        <option value="bottled_other">Bottled/Other (syrups, ointments — sold by the unit)</option>
      </select>
    </div>

    <div id="box-file-fields">
      <div class="field-row">
        <div class="field">
          <label>Tablets per file</label>
          <input type="number" name="tablets_per_file" min="1" value="20">
        </div>
        <div class="field">
          <label>Files per box</label>
          <input type="number" name="files_per_box" min="1" value="12">
        </div>
      </div>
      <div class="field-row">
        <div class="field"><label>Price per box (Rs)</label><input type="number" step="0.01" name="price_per_box" min="0"></div>
        <div class="field"><label>Price per file (Rs)</label><input type="number" step="0.01" name="price_per_file" min="0"></div>
        <div class="field"><label>Price per tablet (Rs)</label><input type="number" step="0.01" name="price_per_tablet" min="0"></div>
      </div>
      <p class="form-preview" id="box-file-preview">1 box = 12 files = 240 tablets</p>
    </div>

    <div id="bottled-fields" style="display:none">
      <div class="field">
        <label>Unit type</label>
        <select name="unit_type" id="unit-type">
          <option>Bottle</option><option>Tube</option><option>Sachet</option>
          <option>Pack</option><option>Strip</option><option>Jar</option><option>Other</option>
        </select>
      </div>
      <div class="field" id="custom-unit-field" style="display:none">
        <label>Custom unit name</label>
        <input type="text" name="custom_unit_name">
      </div>
      <div class="field"><label>Price per unit (Rs)</label><input type="number" step="0.01" name="unit_price" min="0"></div>
    </div>

    <div class="field">
      <label>Low stock threshold</label>
      <input type="number" name="low_stock_threshold" value="10" required>
      <p class="field-hint">Alert when stock falls below this many tablets (or units, for Bottled/Other).</p>
    </div>

    <div class="field">
      <label>Photo (optional)</label>
      <input type="hidden" name="photo_token" id="photo_token">
      <button type="button" id="request-photo-btn" class="btn btn-secondary">Add Photo from Phone</button>
      <span id="photo-status"></span>
    </div>

    <button type="submit" class="btn btn-primary">Save Medicine</button>
  </form>
</div>
{% endblock %}
{% block scripts %}
<script>
var packagingSelect = document.getElementById("packaging-type");
var boxFileFields = document.getElementById("box-file-fields");
var bottledFields = document.getElementById("bottled-fields");

function toggleFields() {
  var isBoxFile = packagingSelect.value === "box_file";
  boxFileFields.style.display = isBoxFile ? "" : "none";
  bottledFields.style.display = isBoxFile ? "none" : "";
}
packagingSelect.addEventListener("change", toggleFields);
toggleFields();

var tabletsInput = document.querySelector('[name="tablets_per_file"]');
var filesInput = document.querySelector('[name="files_per_box"]');
function updatePreview() {
  var tablets = parseInt(tabletsInput.value, 10) || 0;
  var files = parseInt(filesInput.value, 10) || 0;
  document.getElementById("box-file-preview").textContent =
    "1 box = " + files + " files = " + (files * tablets) + " tablets";
}
tabletsInput.addEventListener("input", updatePreview);
filesInput.addEventListener("input", updatePreview);
updatePreview();

var unitTypeSelect = document.getElementById("unit-type");
var customUnitField = document.getElementById("custom-unit-field");
unitTypeSelect.addEventListener("change", function () {
  customUnitField.style.display = unitTypeSelect.value === "Other" ? "" : "none";
});

var photoPollInterval = null;
document.getElementById("request-photo-btn").addEventListener("click", function () {
  if (photoPollInterval) { clearInterval(photoPollInterval); }
  fetch("/photos/new-token", { method: "POST" })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      document.getElementById("photo_token").value = data.token;
      var status = document.getElementById("photo-status");
      status.innerHTML = '<img src="' + data.qr_url + '" alt="Scan with phone" width="120">' + '<br>Waiting for photo...';
      photoPollInterval = setInterval(function () {
        fetch("/photos/status/" + data.token)
          .then(function (r) { return r.json(); })
          .then(function (s) {
            if (s.uploaded) {
              clearInterval(photoPollInterval);
              photoPollInterval = null;
              status.textContent = "Photo received!";
            }
          });
      }, 3000);
    });
});
</script>
{% endblock %}
```

- [ ] **Step 7: Sweep the rest of the test suite for the old add_medicine signature**

Run `grep -rn "add_medicine(" tests/` — for each remaining call site outside `test_inventory.py`, replace it with the new helpers:

In `tests/test_sales.py`: there is exactly one call site — the `_setup_medicine(app, stock_boxes=5)` helper function near the top of the file, which every test in this file calls. Remove the `TABLET_UNITS` constant, remove `add_medicine` from the `from inventory import ...` line (keep `get_medicine`), add `from helpers import make_box_file_medicine`. Inside `_setup_medicine`, replace `medicine_id = add_medicine("Cetamol", "Tablet", 50, TABLET_UNITS)` with `medicine_id = make_box_file_medicine(name="Cetamol", low_stock_threshold=50)` — the helper's defaults (Box 240 units/Rs 480, File 20 units/Rs 45, Tablet 1 unit/Rs 2.5) exactly match `TABLET_UNITS`'s old values, so `_setup_medicine`'s own signature, its `add_stock(medicine_id, "Box", stock_boxes)` line, and every test that calls `_setup_medicine(app)` elsewhere in the file are unaffected.

In `tests/test_dashboard.py`: same replacement — remove `TABLET_UNITS`, `from helpers import make_box_file_medicine`, replace both `add_medicine("Cetamol", "Tablet", 100, TABLET_UNITS)` and `add_medicine("Napa", "Tablet", 100, TABLET_UNITS)` with `make_box_file_medicine(name="Cetamol", low_stock_threshold=100)` / `make_box_file_medicine(name="Napa", low_stock_threshold=100)` respectively.

In `tests/test_users.py`: find the `add_medicine("Paracetamol", "Tablet", 10, [...])` call — replace with `from helpers import make_box_file_medicine` at the top of that test function (or file-level import) and `make_box_file_medicine(name="Paracetamol", low_stock_threshold=10)`.

- [ ] **Step 8: Run the full test suite to confirm everything passes**

Run: `pytest -v`
Expected: all tests PASS — this is the critical checkpoint for this task, since the signature change is breaking

- [ ] **Step 9: Commit**

```bash
git add schema.sql inventory.py templates/medicine_add.html tests/helpers.py tests/test_inventory.py tests/test_sales.py tests/test_dashboard.py tests/test_users.py
git commit -m "feat: category-driven packaging model (box_file/bottled_other) replaces freeform units"
```

---

### Task 3: Products & Add Stock pages restyle

**Files:**
- Modify: `templates/medicines.html`
- Modify: `templates/add_stock.html`

**Interfaces:**
- Consumes: `inventory.list_medicines_view`'s existing `medicines`/`price_breakdowns` context (unchanged from Task 2), `inventory.add_stock_view`'s existing `medicine`/`units` context (unchanged).

- [ ] **Step 1: Rewrite templates/medicines.html**

```html
{% extends "base.html" %}
{% block page_title %}Products{% endblock %}
{% block page_desc %}Manage your medicine catalog, stock levels, and pricing.{% endblock %}
{% block content %}
<div class="panel-head" style="margin-bottom:14px">
  <div></div>
  {% if session.get('role') == 'admin' %}
  <a href="{{ url_for('inventory.add_medicine_view') }}" class="btn btn-primary">+ Add Medicine</a>
  {% endif %}
</div>
<div class="card panel">
  <div class="table-scroll">
    <table>
      <thead><tr><th></th><th>Medicine</th><th>Category</th><th>Price</th><th class="num">Stock</th><th>Status</th><th></th></tr></thead>
      <tbody>
      {% for m in medicines %}
      <tr>
        <td>
          <div class="thumb">
            {% if m['photo_path'] %}<img src="{{ url_for('static', filename=m['photo_path']) }}" alt="">
            {% else %}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="7" width="18" height="13" rx="2"></rect></svg>{% endif %}
          </div>
        </td>
        <td><div class="med-name">{{ m['name'] }}</div></td>
        <td>{{ "Box/File" if m['packaging_type'] == "box_file" else "Bottled/Other" }}</td>
        <td>
          {% for b in price_breakdowns[m['id']] %}
          <div class="med-sub num">{{ b['unit_name'] }}: Rs {{ "%.2f"|format(b['price']) }}</div>
          {% endfor %}
        </td>
        <td class="num">{{ m['stock_in_base_units'] }}</td>
        <td>
          {% if m['stock_in_base_units'] < m['low_stock_threshold'] %}
          <span class="badge warn">Low Stock</span>
          {% else %}
          <span class="badge good">In Stock</span>
          {% endif %}
        </td>
        <td>
          {% if session.get('role') == 'admin' %}
          <a href="{{ url_for('inventory.add_stock_view', medicine_id=m['id']) }}" class="btn btn-secondary btn-icon">Add Stock</a>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% if not medicines %}
  <p class="panel-desc">No medicines yet.</p>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 2: Rewrite templates/add_stock.html**

```html
{% extends "base.html" %}
{% block page_title %}Add Stock{% endblock %}
{% block page_desc %}Record newly arrived stock for {{ medicine['name'] }}.{% endblock %}
{% block content %}
<div class="card panel" style="max-width:420px">
  <form method="post" class="styled-form">
    <div class="field">
      <label>Unit</label>
      <select name="unit_name" required>
        {% for u in units %}
        <option value="{{ u['unit_name'] }}">{{ u['unit_name'] }} (1 = {{ u['qty_in_base_units'] }} base unit{{ 's' if u['qty_in_base_units'] != 1 }})</option>
        {% endfor %}
      </select>
    </div>
    <div class="field">
      <label>Quantity received</label>
      <input type="number" name="quantity" min="1" required autofocus>
    </div>
    <button type="submit" class="btn btn-primary">Add Stock</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `pytest -v`
Expected: all tests PASS (this task is presentation-only; `test_list_medicines_view_shows_price_breakdown_and_photo`-style assertions in `test_inventory.py` check for price/photo text, which is still present)

- [ ] **Step 4: Commit**

```bash
git add templates/medicines.html templates/add_stock.html
git commit -m "style: restyle Products and Add Stock pages with the design system"
```

---

### Task 4: Dashboard restyle

**Files:**
- Modify: `dashboard.py`
- Modify: `templates/dashboard.html`
- Modify: `tests/test_dashboard.py` (extend)

**Interfaces:**
- Consumes: `inventory.count_medicines()` (from Task 2), `inventory.low_stock_medicines()`, `sales.today_sales_total()`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_dashboard.py
def test_dashboard_shows_total_products(admin_client, app):
    with app.app_context():
        from helpers import make_box_file_medicine
        make_box_file_medicine(name="Cetamol")
        make_box_file_medicine(name="Napa")

    response = admin_client.get("/")
    assert response.status_code == 200
    assert b'"value">2</div>' in response.data
```

This matches `dashboard.html`'s `<div class="value">{{ total_products }}</div>` exactly (Step 4 below), so it can't false-positive on some other "2" elsewhere on the page (e.g. a stock count or threshold).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard.py -v`
Expected: FAIL — `dashboard.html` has no such markup yet

- [ ] **Step 3: Modify dashboard.py**

```python
from flask import Blueprint, render_template

from auth import login_required
from inventory import count_medicines, low_stock_medicines
from sales import today_sales_total

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def home():
    return render_template(
        "dashboard.html",
        low_stock=low_stock_medicines(),
        todays_total=today_sales_total(),
        total_products=count_medicines(),
    )
```

- [ ] **Step 4: Rewrite templates/dashboard.html**

```html
{% extends "base.html" %}
{% block page_title %}Dashboard{% endblock %}
{% block page_desc %}Overview of today's sales and stock that needs attention.{% endblock %}
{% block content %}
<div class="stat-row">
  <div class="card stat-card">
    <div class="label">Revenue Today</div>
    <div class="value">Rs {{ "%.2f"|format(todays_total) }}</div>
  </div>
  <div class="card stat-card">
    <div class="label">Total Products</div>
    <div class="value">{{ total_products }}</div>
  </div>
  <div class="card stat-card {{ 'alert' if low_stock }}">
    <div class="label">Low Stock</div>
    <div class="value">{{ low_stock|length }}</div>
    <div class="sub">{{ "Need reordering soon" if low_stock else "All good" }}</div>
  </div>
</div>

<div class="action-row">
  <a class="action-card card" href="{{ url_for('sales.new_sale') }}">
    <div class="icon-badge"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="14" rx="2"></rect></svg></div>
    <div class="title">New Sale</div>
    <div class="desc">Search a medicine and check out a customer</div>
    <div class="go">Open POS →</div>
  </a>
  <a class="action-card card" href="{{ url_for('inventory.list_medicines_view') }}">
    <div class="icon-badge"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v3"></path></svg></div>
    <div class="title">Products</div>
    <div class="desc">Add medicines, restock, edit pricing</div>
    <div class="go">Manage →</div>
  </a>
  <a class="action-card card" href="{{ url_for('sales.list_sales_view') }}">
    <div class="icon-badge"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"></path></svg></div>
    <div class="title">Sales History</div>
    <div class="desc">Look up a past sale, void if needed</div>
    <div class="go">View →</div>
  </a>
  {% if session.get('role') == 'admin' %}
  <a class="action-card card" href="{{ url_for('users.list_users') }}">
    <div class="icon-badge"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle></svg></div>
    <div class="title">Staff</div>
    <div class="desc">Add or remove staff login accounts</div>
    <div class="go">Manage →</div>
  </a>
  {% endif %}
</div>

<div class="card panel">
  <div class="panel-head">
    <div>
      <h2>Medicines running low</h2>
      <p class="panel-desc">Below their restock threshold.</p>
    </div>
  </div>
  {% if low_stock %}
  <div class="table-scroll">
    <table>
      <thead><tr><th>Medicine</th><th class="num">Stock</th><th class="num">Threshold</th></tr></thead>
      <tbody>
      {% for m in low_stock %}
      <tr><td>{{ m['name'] }}</td><td class="num">{{ m['stock_in_base_units'] }}</td><td class="num">{{ m['low_stock_threshold'] }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <p class="panel-desc">No medicines are low on stock.</p>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_dashboard.py -v`
Expected: PASS

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add dashboard.py templates/dashboard.html tests/test_dashboard.py
git commit -m "feat: dashboard shows total products stat, restyled with quick actions"
```

---

### Task 5: POS keyboard-first search + quantity modal

**Files:**
- Modify: `sales.py` (search route)
- Modify: `templates/new_sale.html` (full rewrite)
- Modify: `tests/test_sales.py` (extend)

**Interfaces:**
- Consumes: `inventory.sellable_units` (from Task 2, replaces `get_medicine_units` in this route), `inventory.search_medicines`.
- Produces: `/sales/search` now returns `packaging_type` and `photo_path` per medicine alongside `id`/`name`/`units`, and `units` only contains sellable rows.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_sales.py
def test_sales_search_excludes_box_unit(admin_client, app):
    from helpers import make_box_file_medicine
    with app.app_context():
        make_box_file_medicine(name="Cetamol")
    response = admin_client.get("/sales/search?q=ceta")
    data = response.get_json()
    unit_names = {u["unit_name"] for u in data[0]["units"]}
    assert unit_names == {"File", "Tablet"}
    assert "photo_path" in data[0]
    assert "packaging_type" in data[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sales.py -v -k search_excludes_box`
Expected: FAIL — search still returns all units including Box, and no `photo_path`/`packaging_type` keys

- [ ] **Step 3: Modify sales.py's search route**

```python
# change the import line near the top of sales.py from:
# from inventory import get_medicine_units, search_medicines
# to:
from inventory import search_medicines, sellable_units
```

```python
# replace the existing search() route body with:
@bp.route("/search")
@login_required
def search():
    query = request.args.get("q", "")
    medicines = search_medicines(query)
    results = []
    for m in medicines:
        units = sellable_units(m["id"])
        results.append({
            "id": m["id"],
            "name": m["name"],
            "packaging_type": m["packaging_type"],
            "photo_path": m["photo_path"],
            "units": [{"unit_name": u["unit_name"], "price": u["price"]} for u in units],
        })
    return jsonify(results)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sales.py -v -k search_excludes_box`
Expected: PASS

- [ ] **Step 5: Add the CSS this page needs (append to static/style.css)**

```css
/* append — POS page specific additions on top of Task 1's design system */
.bill-total-row { text-align:right; font-weight:700; font-size:15px; padding:10px 0; }
```

(If `.bill-total-row` and `.search-results`/`.search-result` are already present from Task 1, skip — check the file first; Task 1's stylesheet already includes `.search-results`/`.search-result`/`.bill-total-row`, so this step is likely a no-op verification, not a real addition. Only add rules that are genuinely missing.)

- [ ] **Step 6: Rewrite templates/new_sale.html**

```html
{% extends "base.html" %}
{% block page_title %}Point of Sale{% endblock %}
{% block page_desc %}Search for a medicine, add it to the bill, then finalize to print a receipt. Press F2 anytime to finalize.{% endblock %}
{% block content %}
<div class="card panel">
  <div class="search-box">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"></circle><path d="m21 21-4.3-4.3"></path></svg>
    <input type="text" id="search-box" placeholder="Search medicine by name…" autocomplete="off" autofocus>
  </div>
  <div id="search-results" class="search-results"></div>
</div>

<div class="card panel">
  <div class="panel-head">
    <div>
      <h2>Current Bill</h2>
      <p class="panel-desc">Press <span class="kbd">F2</span> to finalize once you're done adding items.</p>
    </div>
  </div>
  <div id="bill-error" class="banner-error" style="display:none"></div>
  <div class="table-scroll">
    <table id="bill-table">
      <thead><tr><th>Medicine</th><th>Unit</th><th class="num">Qty</th><th class="num">Price</th><th class="num">Subtotal</th><th></th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
  <div class="bill-total-row">Total: <span class="num" id="bill-total">Rs 0.00</span></div>
  <button type="button" id="finalize-btn" class="btn btn-primary">Finalize Sale (F2)</button>
</div>

<div class="modal-backdrop" id="qty-modal">
  <div class="modal">
    <h3 id="qty-modal-title">Add to bill</h3>
    <div id="qty-modal-error" class="banner-error" style="display:none"></div>
    <div class="field">
      <label>Unit</label>
      <div class="unit-toggle" id="unit-toggle"></div>
    </div>
    <div class="field">
      <label>Quantity</label>
      <input type="number" id="qty-input" min="1" value="1">
    </div>
    <div class="modal-actions">
      <button type="button" class="btn btn-secondary" onclick="closeModal('qty-modal')">Cancel</button>
      <button type="button" class="btn btn-primary" id="qty-confirm-btn">Add (Enter)</button>
    </div>
  </div>
</div>
{% endblock %}
{% block scripts %}
<script>
var bill = [];
var currentResults = [];
var highlightedIndex = -1;
var activeMedicine = null;
var activeUnitIndex = 0;

var searchInput = document.getElementById("search-box");
var resultsBox = document.getElementById("search-results");

function renderResults() {
  resultsBox.innerHTML = "";
  currentResults.forEach(function (m, i) {
    var row = document.createElement("div");
    row.className = "search-result" + (i === highlightedIndex ? " highlighted" : "");
    var thumb = m.photo_path
      ? '<img src="/static/' + m.photo_path + '" alt="">'
      : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="7" width="18" height="13" rx="2"></rect></svg>';
    row.innerHTML = '<div class="thumb">' + thumb + '</div><div><div class="med-name">' + m.name +
      '</div><div class="med-sub">' + (m.packaging_type === "box_file" ? "Box/File" : "Bottled/Other") + '</div></div>';
    row.addEventListener("click", function () { selectMedicine(i); });
    resultsBox.appendChild(row);
  });
}

function selectMedicine(index) {
  activeMedicine = currentResults[index];
  activeUnitIndex = 0;
  if (!activeMedicine || activeMedicine.units.length === 0) { return; }
  document.getElementById("qty-modal-title").textContent = "Add " + activeMedicine.name;
  document.getElementById("qty-modal-error").style.display = "none";
  document.getElementById("qty-input").value = 1;
  renderUnitToggle();
  openModal("qty-modal");
  document.getElementById("qty-input").focus();
}

function renderUnitToggle() {
  var toggle = document.getElementById("unit-toggle");
  toggle.innerHTML = "";
  activeMedicine.units.forEach(function (u, i) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary" + (i === activeUnitIndex ? " selected" : "");
    btn.textContent = u.unit_name + " (Rs " + u.price.toFixed(2) + ")";
    btn.addEventListener("click", function () { activeUnitIndex = i; renderUnitToggle(); });
    toggle.appendChild(btn);
  });
}

searchInput.addEventListener("input", function (e) {
  var q = e.target.value;
  highlightedIndex = -1;
  if (!q) { currentResults = []; renderResults(); return; }
  fetch("/sales/search?q=" + encodeURIComponent(q))
    .then(function (r) { return r.json(); })
    .then(function (medicines) {
      currentResults = medicines.filter(function (m) { return m.units.length > 0; });
      highlightedIndex = currentResults.length ? 0 : -1;
      renderResults();
    });
});

searchInput.addEventListener("keydown", function (e) {
  if (e.key === "ArrowDown") {
    e.preventDefault();
    if (currentResults.length) { highlightedIndex = Math.min(highlightedIndex + 1, currentResults.length - 1); renderResults(); }
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    if (currentResults.length) { highlightedIndex = Math.max(highlightedIndex - 1, 0); renderResults(); }
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (highlightedIndex >= 0) { selectMedicine(highlightedIndex); }
  }
});

document.getElementById("qty-input").addEventListener("keydown", function (e) {
  if (e.key === "Tab" || e.key === "ArrowRight") {
    e.preventDefault();
    activeUnitIndex = (activeUnitIndex + 1) % activeMedicine.units.length;
    renderUnitToggle();
  } else if (e.key === "ArrowLeft") {
    e.preventDefault();
    activeUnitIndex = (activeUnitIndex - 1 + activeMedicine.units.length) % activeMedicine.units.length;
    renderUnitToggle();
  } else if (e.key === "Enter") {
    e.preventDefault();
    confirmAddToBill();
  }
});
document.getElementById("qty-confirm-btn").addEventListener("click", confirmAddToBill);

function confirmAddToBill() {
  var quantity = parseInt(document.getElementById("qty-input").value, 10);
  var errorBox = document.getElementById("qty-modal-error");
  if (!quantity || quantity <= 0) {
    errorBox.textContent = "Enter a quantity of at least 1.";
    errorBox.style.display = "block";
    return;
  }
  var unit = activeMedicine.units[activeUnitIndex];
  bill.push({
    medicine_id: activeMedicine.id, name: activeMedicine.name,
    unit_name: unit.unit_name, price: unit.price, quantity: quantity,
  });
  renderBill();
  closeModal("qty-modal");
  searchInput.value = "";
  currentResults = [];
  renderResults();
  searchInput.focus();
}

function renderBill() {
  var tbody = document.querySelector("#bill-table tbody");
  tbody.innerHTML = "";
  var total = 0;
  bill.forEach(function (item, i) {
    var subtotal = item.price * item.quantity;
    total += subtotal;
    var row = tbody.insertRow();
    row.innerHTML = "<td>" + item.name + "</td><td>" + item.unit_name + "</td>" +
      "<td class=\"num\">" + item.quantity + "</td><td class=\"num\">" + item.price.toFixed(2) + "</td>" +
      "<td class=\"num\">" + subtotal.toFixed(2) + "</td><td></td>";
    var removeCell = row.cells[5];
    var removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "btn btn-secondary btn-icon";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", function () { bill.splice(i, 1); renderBill(); });
    removeCell.appendChild(removeBtn);
  });
  document.getElementById("bill-total").textContent = "Rs " + total.toFixed(2);
}

function finalizeSale() {
  var errorBox = document.getElementById("bill-error");
  errorBox.style.display = "none";
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
      if (data.error) {
        errorBox.textContent = data.error;
        errorBox.style.display = "block";
        return;
      }
      window.location = "/sales/" + data.sale_id + "/receipt";
    });
}
document.getElementById("finalize-btn").addEventListener("click", finalizeSale);
document.addEventListener("keydown", function (e) {
  if (e.key === "F2") { e.preventDefault(); finalizeSale(); }
});

renderBill();
</script>
{% endblock %}
```

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: all tests PASS

- [ ] **Step 8: Commit**

```bash
git add sales.py templates/new_sale.html static/style.css tests/test_sales.py
git commit -m "feat: keyboard-first POS flow with quantity modal, box units excluded from sale"
```

---

### Task 6: Sales History + receipt seller attribution + void confirm modal

**Files:**
- Modify: `sales.py` (`get_sale`, `list_sales`)
- Modify: `templates/sales_list.html`
- Modify: `templates/receipt.html`
- Modify: `tests/test_sales.py` (extend)

**Interfaces:**
- Produces: `get_sale(sale_id)`'s returned `sale` row and `list_sales(user_id=None)`'s rows now carry a `username` column (joined from `users`).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_sales.py
# _setup_medicine(app, stock_boxes=5) already exists near the top of this file (fixed in
# Task 2 to call make_box_file_medicine internally) and is used by every other test below —
# reuse it here too rather than building a medicine a new way.
def test_get_sale_includes_seller_username(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("cashier1", "pw", "staff")
        result = create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 2}])
        sale = get_sale(result["sale_id"])
        assert sale["sale"]["username"] == "cashier1"


def test_list_sales_includes_seller_username(app):
    medicine_id = _setup_medicine(app)
    with app.app_context():
        from auth import create_user
        user_id = create_user("cashier1", "pw", "staff")
        create_sale(user_id, [{"medicine_id": medicine_id, "unit_name": "Tablet", "quantity": 1}])
        sales = list_sales()
        assert sales[0]["username"] == "cashier1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sales.py -v -k seller_username`
Expected: FAIL — `KeyError: 'username'` (neither query joins `users` yet)

- [ ] **Step 3: Modify sales.py's get_sale and list_sales**

```python
# replace the existing get_sale function body's sale query with a join:
def get_sale(sale_id):
    db = get_db()
    sale = db.execute(
        "SELECT s.*, u.username FROM sales s JOIN users u ON u.id = s.user_id WHERE s.id = ?",
        (sale_id,),
    ).fetchone()
    if sale is None:
        return None
    items = db.execute(
        "SELECT si.*, m.name AS medicine_name FROM sale_items si "
        "JOIN medicines m ON m.id = si.medicine_id WHERE si.sale_id = ?",
        (sale_id,),
    ).fetchall()
    return {"sale": sale, "items": items}
```

```python
# replace the existing list_sales function entirely with:
def list_sales(user_id=None):
    db = get_db()
    if user_id is None:
        return db.execute(
            "SELECT s.*, u.username FROM sales s JOIN users u ON u.id = s.user_id "
            "ORDER BY s.id DESC LIMIT 50"
        ).fetchall()
    return db.execute(
        "SELECT s.*, u.username FROM sales s JOIN users u ON u.id = s.user_id "
        "WHERE s.user_id = ? ORDER BY s.id DESC LIMIT 50",
        (user_id,),
    ).fetchall()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sales.py -v -k seller_username`
Expected: PASS

- [ ] **Step 5: Rewrite templates/sales_list.html**

```html
{% extends "base.html" %}
{% block page_title %}Sales History{% endblock %}
{% block page_desc %}Browse past sales; admins can void one to restore its stock.{% endblock %}
{% block content %}
<div class="card panel">
  <div class="table-scroll">
    <table>
      <thead><tr><th>Date/Time</th><th>Sold By</th><th class="num">Total</th><th>Status</th><th></th></tr></thead>
      <tbody>
      {% for s in sales %}
      <tr>
        <td>{{ s['timestamp'] }}</td>
        <td>{{ s['username'] }}</td>
        <td class="num">Rs {{ "%.2f"|format(s['total']) }}</td>
        <td>{% if s['voided'] %}<span class="badge critical">Voided</span>{% else %}<span class="badge good">Completed</span>{% endif %}</td>
        <td><a href="{{ url_for('sales.receipt', sale_id=s['id']) }}" class="btn btn-secondary btn-icon">Receipt</a></td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% if not sales %}
  <p class="panel-desc">No sales recorded yet.</p>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 6: Rewrite templates/receipt.html**

```html
{% extends "base.html" %}
{% block page_title %}Receipt #{{ sale['id'] }}{% endblock %}
{% block page_desc %}{% if sale['voided'] %}This sale has been voided.{% else %}Printable record of this sale.{% endif %}{% endblock %}
{% block content %}
<div class="card panel" style="max-width:520px">
  {% if sale['voided'] %}<span class="badge critical">Voided</span>{% endif %}
  <p class="panel-desc">Date: {{ sale['timestamp'] }} · Sold by: {{ sale['username'] }}</p>
  <div class="table-scroll">
    <table>
      <thead><tr><th>Medicine</th><th>Unit</th><th class="num">Qty</th><th class="num">Price</th><th class="num">Subtotal</th></tr></thead>
      <tbody>
      {% for item in items %}
      <tr>
        <td>{{ item['medicine_name'] }}</td>
        <td>{{ item['unit_name'] }}</td>
        <td class="num">{{ item['quantity'] }}</td>
        <td class="num">{{ "%.2f"|format(item['unit_price']) }}</td>
        <td class="num">{{ "%.2f"|format(item['subtotal']) }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  <div class="bill-total-row">Total: Rs {{ "%.2f"|format(sale['total']) }}</div>
  <div class="no-print" style="display:flex; gap:10px; margin-top:16px;">
    <button class="btn btn-secondary" onclick="window.print()">Print</button>
    {% if session.get('role') == 'admin' and not sale['voided'] %}
    <button type="button" class="btn btn-danger" onclick="openModal('void-modal')">Void Sale</button>
    {% endif %}
  </div>
</div>

{% if session.get('role') == 'admin' and not sale['voided'] %}
<div class="modal-backdrop" id="void-modal">
  <div class="modal">
    <h3>Void this sale?</h3>
    <p>Stock will be restored for every item on this receipt. This cannot be undone.</p>
    <div class="modal-actions">
      <button type="button" class="btn btn-secondary" onclick="closeModal('void-modal')">Cancel</button>
      <form method="post" action="{{ url_for('sales.void', sale_id=sale['id']) }}">
        <button type="submit" class="btn btn-danger">Void Sale</button>
      </form>
    </div>
  </div>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: all tests PASS

- [ ] **Step 8: Commit**

```bash
git add sales.py templates/sales_list.html templates/receipt.html tests/test_sales.py
git commit -m "feat: show seller on sales history/receipt, void confirmed via modal"
```

---

### Task 7: Admin resets staff password

**Files:**
- Modify: `users.py` (`reset_staff_password`, `reset_password` route)
- Modify: `templates/users.html` (full rewrite — reset-password modal + remove-confirm modal)
- Modify: `tests/test_users.py` (extend)

**Interfaces:**
- Produces: `users.reset_staff_password(user_id, new_password) -> None` (raises `ValueError` if target isn't a staff account or password is empty), route `users.reset_password`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_users.py
def test_reset_staff_password_updates_password(app):
    with app.app_context():
        from auth import create_user, verify_login
        from users import reset_staff_password
        user_id = create_user("staff1", "oldpass", "staff")
        reset_staff_password(user_id, "newpass123")
        assert verify_login("staff1", "newpass123") is not None
        assert verify_login("staff1", "oldpass") is None


def test_reset_staff_password_refuses_admin_target(app):
    with app.app_context():
        import pytest
        from auth import create_user
        from users import reset_staff_password
        admin_id = create_user("admin", "pw", "admin")
        with pytest.raises(ValueError):
            reset_staff_password(admin_id, "newpass123")


def test_reset_password_route_requires_admin(staff_client, app):
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff2", "pw", "staff")
    response = staff_client.post(f"/users/{user_id}/reset-password", data={"new_password": "newpass123"})
    assert response.status_code == 403


def test_reset_password_route_updates_and_redirects(admin_client, app):
    with app.app_context():
        from auth import create_user
        user_id = create_user("staff2", "oldpass", "staff")
    response = admin_client.post(f"/users/{user_id}/reset-password", data={"new_password": "newpass123"})
    assert response.status_code == 302
    with app.app_context():
        from auth import verify_login
        assert verify_login("staff2", "newpass123") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_users.py -v -k reset_password`
Expected: FAIL — `ImportError: cannot import name 'reset_staff_password'`

- [ ] **Step 3: Modify users.py**

```python
# change the import line near the top of users.py from:
# from auth import create_user, role_required
# to:
from auth import create_user, role_required
from werkzeug.security import generate_password_hash
```

```python
# add near delete_staff
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
```

```python
# add near delete_user route
@bp.route("/<int:user_id>/reset-password", methods=["POST"])
@role_required("admin")
def reset_password(user_id):
    try:
        reset_staff_password(user_id, request.form.get("new_password", ""))
        flash("Password reset.")
    except ValueError as e:
        flash(str(e))
    return redirect(url_for("users.list_users"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_users.py -v -k reset_password`
Expected: PASS

- [ ] **Step 5: Rewrite templates/users.html**

```html
{% extends "base.html" %}
{% block page_title %}Staff Accounts{% endblock %}
{% block page_desc %}Add, remove, or reset passwords for staff logins.{% endblock %}
{% block content %}
<div class="card panel">
  <div class="table-scroll">
    <table>
      <thead><tr><th>Username</th><th></th></tr></thead>
      <tbody>
      {% for s in staff %}
      <tr>
        <td>{{ s['username'] }}</td>
        <td style="display:flex; gap:8px;">
          <button type="button" class="btn btn-secondary btn-icon" onclick="openModal('reset-modal-{{ s['id'] }}')">Reset Password</button>
          <button type="button" class="btn btn-danger btn-icon" onclick="openModal('remove-modal-{{ s['id'] }}')">Remove</button>
        </td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% if not staff %}<p class="panel-desc">No staff accounts yet.</p>{% endif %}
</div>

{% for s in staff %}
<div class="modal-backdrop" id="reset-modal-{{ s['id'] }}">
  <div class="modal">
    <h3>Reset password for {{ s['username'] }}</h3>
    <form method="post" action="{{ url_for('users.reset_password', user_id=s['id']) }}" class="styled-form">
      <div class="field">
        <label>New password</label>
        <input type="password" name="new_password" required minlength="6" autofocus>
      </div>
      <div class="modal-actions">
        <button type="button" class="btn btn-secondary" onclick="closeModal('reset-modal-{{ s['id'] }}')">Cancel</button>
        <button type="submit" class="btn btn-primary">Reset Password</button>
      </div>
    </form>
  </div>
</div>
<div class="modal-backdrop" id="remove-modal-{{ s['id'] }}">
  <div class="modal">
    <h3>Remove {{ s['username'] }}?</h3>
    <p>They will no longer be able to log in. This cannot be undone.</p>
    <div class="modal-actions">
      <button type="button" class="btn btn-secondary" onclick="closeModal('remove-modal-{{ s['id'] }}')">Cancel</button>
      <form method="post" action="{{ url_for('users.delete_user', user_id=s['id']) }}">
        <button type="submit" class="btn btn-danger">Remove</button>
      </form>
    </div>
  </div>
</div>
{% endfor %}

<div class="card panel">
  <h2>Add Staff Account</h2>
  <form method="post" action="{{ url_for('users.add_user') }}" class="styled-form">
    <div class="field">
      <label>Username</label>
      <input type="text" name="username" required>
    </div>
    <div class="field">
      <label>Password</label>
      <input type="password" name="password" required minlength="6">
    </div>
    <button type="submit" class="btn btn-primary">Add Staff Account</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add users.py templates/users.html tests/test_users.py
git commit -m "feat: admin can reset a staff member's password, remove/reset confirmed via modal"
```

---

### Task 8: Dialog sweep, page-description verification, and manual walkthrough

**Files:** none created — verification and cleanup only.

- [ ] **Step 1: Grep for any remaining native browser dialogs**

Run: `grep -rn "alert(\|confirm(\|prompt(" templates/ static/`
Expected: no matches (the only pre-existing use, the quantity `prompt()` in the old `new_sale.html`, was replaced in Task 5; the old `alert(data.error)` was replaced with the inline `#bill-error` banner in Task 5). If anything turns up, replace it with the modal pattern established in Tasks 5–7 (a `.modal-backdrop`/`.modal` pair plus `openModal`/`closeModal`) or an inline `.banner-error`, matching whichever pattern the surrounding page already uses.

- [ ] **Step 2: Confirm every authenticated page fills page_title/page_desc**

Run: `grep -L "block page_title" templates/*.html` — every template that extends `base.html` and is reachable by a logged-in user (i.e. everything except `login.html`, which uses `auth_content` instead) should NOT appear in this output. If one does, add the missing `{% block page_title %}`/`{% block page_desc %}` pair.

- [ ] **Step 3: Run the full automated test suite**

Run: `pytest -v`
Expected: all tests PASS

- [ ] **Step 4: Manual verification (document what's verifiable from the command line vs. what needs a human with a browser)**

From the command line: confirm the CLI bootstrap still works (`flask --app app init-admin admin adminpass` against a throwaway DB copy), confirm no stray `pharmacy.db`/photo files were left in the working tree (`git status` clean), confirm the full suite is green.

Needs a human with a browser (list explicitly in the task report rather than claiming to have done it): the sidebar renders correctly and highlights the active page; the Add Medicine form's category toggle and live box/file/tablet preview work; the POS page's keyboard flow (arrow keys through search results, Enter opens the modal, Tab/arrow switches unit, Enter adds to bill, F2 finalizes) feels usable without a mouse; all modals (quantity, void confirm, remove-staff confirm, reset-password) open/close correctly including Escape and backdrop-click; the print preview on the receipt page looks reasonable; dark mode (if the OS is set to dark) doesn't break contrast anywhere.

- [ ] **Step 5: Commit (only if Steps 1–2 required any fixes; otherwise skip — nothing to commit for a clean sweep)**

```bash
git add -A
git commit -m "chore: verify no native dialogs remain and every page has a description"
```
