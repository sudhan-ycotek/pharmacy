# Pharmacy Inventory & Billing System — Design

## Context

Building a local inventory management system for a pharmacy, to run on the owner's (user's sister's) computer only — no internet/hosting required. Goal: smooth out stock tracking and sales/billing, which are currently manual. Priority is a basic, no-frills UI — functionality over polish. Project directory started empty; this is a from-scratch build.

## Tech Stack

- **Backend**: Python + Flask
- **Database**: SQLite (single file, `pharmacy.db`) — trivial backup (copy the file), no DB server to install/maintain
- **Frontend**: Server-rendered Jinja2 templates + minimal CSS. No JS framework. Small vanilla JS only where needed: live search-as-you-type on the sale screen, and background polling for the photo-upload QR flow.
- **Extra libraries**: `qrcode` (QR generation, pure local, no internet), `Pillow` (image handling for photos/QR), Werkzeug's built-in password hashing (ships with Flask, no extra dep).

## Data Model

- **medicines**: `id, name, category, photo_path, stock_in_base_units, low_stock_threshold`
- **medicine_units** (variable packaging levels per medicine, ordered largest→smallest): `id, medicine_id, unit_name, qty_in_base_units, price`
  - Example for a tablet medicine: Box (qty=240), File (qty=20), Tablet (qty=1, base unit).
  - Example for a liquid: just one row, e.g. Bottle (qty=1, base unit).
  - Stock is always stored/decremented in base units internally; other levels exist purely for display + pricing (per-tablet price shown for reference, computed from the box/file price).
- **users**: `id, username, password_hash, role` (`admin` | `staff`)
- **sales**: `id, user_id, timestamp, total, voided`
- **sale_items**: `id, sale_id, medicine_id, unit_name, quantity, unit_price, subtotal`
- **photo_tokens**: `token, photo_path, expires_at, used` — not tied to a medicine_id until the form that requested it is submitted (so it works for brand-new medicines too)

No batch/expiry tracking and no supplier tracking in this version (explicitly descoped to keep v1 lean; can be added later without restructuring the core model).

## Features

### Auth & Roles
- Login page, Flask session cookie.
- **Admin** (sister): full access — manage medicines/units/prices, manage stock, sell, view all reports, void sales, add/remove staff accounts.
- **Staff**: sell medicines, view stock, view own sales. Cannot edit prices/medicines, delete anything, void sales, or manage users.
- Passwords hashed via Werkzeug.

### Medicine & Stock Management
- Add medicine: name, category, one or more packaging unit levels (name + qty-in-base-units + price each), low-stock threshold, optional photo.
- Add stock: pick existing medicine, add quantity (in whichever unit level makes sense — converts to base units internally).

### Sales / Billing
1. "New Sale" page — live search box filters medicines by name as you type.
2. Pick medicine, pick unit level to sell at (whatever units that medicine has), enter quantity — price auto-fills, item added to a running bill.
3. Add multiple medicines to one bill before finalizing.
4. Finalize → stock decremented (converted to base units), sale + sale_items saved, itemized receipt shown on-screen with a print button (print-friendly CSS, `@media print`, no PDF library needed).
5. **Admin only**: void a completed sale → restores stock, marks sale as voided (kept in history, not deleted, for auditability).

### Photo Upload (QR handoff)
- On "Add Medicine" / "Add Stock" pages, an "Add Photo from Phone" button generates a one-time token + QR code (valid ~10 min, single-use).
- Scanning opens a mobile-friendly page `/upload_photo/<token>` with a camera-capture file input — phone user snaps/picks a photo and uploads.
- Desktop page polls quietly in the background (small JS `fetch` loop) and shows a thumbnail once the upload lands, then stops polling.
- Photo gets linked to the medicine record when that page's form is submitted.

### Dashboard (home page after login)
- Low-stock list: medicines where `stock_in_base_units` is below their configured threshold.
- Today's total sales (sum of non-voided sales, filtered to today's date).

### Network Access (LAN, no internet)
- Launcher starts Flask bound to `0.0.0.0` (not just `localhost`) so devices on the same network can reach it, then opens the desktop's default browser to `localhost:5000`.
- Phone connects via the PC's LAN IP (e.g. `192.168.1.5:5000`) over the same WiFi/router — no internet connection required at any point; QR codes just encode a local URL.

### Deployment
- Everything lives in one project folder + the `pharmacy.db` file.
- `run.bat`: double-clickable launcher that starts the Flask server and opens the browser — no command line needed for day-to-day use.
- Backup = copy the folder (specifically `pharmacy.db` matters most).

## Project Structure

```
pharmacy/
  app.py               # Flask app, routes
  models.py            # DB access layer (SQLite)
  schema.sql           # table definitions, run once to init pharmacy.db
  templates/
    login.html
    dashboard.html
    medicines.html      # list/add/edit medicines + units
    add_stock.html
    new_sale.html
    receipt.html
    upload_photo.html   # mobile-facing page
    users.html          # admin: manage staff accounts
  static/
    style.css
    photos/             # uploaded medicine photos
  requirements.txt      # Flask, qrcode, Pillow
  run.bat
  pharmacy.db           # created on first run
```

## Verification Plan

1. `pip install -r requirements.txt`, run `schema.sql` against a fresh `pharmacy.db`, seed one admin account.
2. Double-click `run.bat` → browser opens, log in as admin.
3. Add a tablet-style medicine with Box/File/Tablet units + prices; confirm per-tablet price displays correctly.
4. Add a liquid-style medicine with a single unit; confirm it doesn't show irrelevant unit fields.
5. Add stock to both; confirm `stock_in_base_units` updates correctly with unit conversion.
6. Log in as a staff account; confirm restricted actions (edit price, delete, void, manage users) are blocked/hidden.
7. Make a multi-item sale mixing unit levels (e.g. 2 tablets + 1 box of another medicine); confirm stock decrements correctly and receipt totals are right; test print preview.
8. Void the sale as admin; confirm stock is restored and sale shows as voided in history, not deleted.
9. Drop stock below threshold; confirm it appears on the dashboard low-stock list. Confirm today's sales total matches expectations.
10. From a phone on the same WiFi, browse to the PC's LAN IP; confirm the app loads.
11. From the desktop "Add Medicine" page, generate a QR, scan with phone, upload a photo, confirm it appears on desktop without manual refresh.
