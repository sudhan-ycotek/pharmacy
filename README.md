# Pharmacy Inventory & Billing System

Local-only inventory and sales system. Runs on one computer, no internet required.

There are two ways to run this: from source (needs Python installed), or as a
single packaged `.exe` (nothing to install, easier to hand to someone else
without also handing them the source code). Pick one.

## Option A: Packaged .exe (recommended for handing off to someone else)

**Building it** (do this once, on any Windows PC with Python installed — the
result is a single file you can then copy anywhere):
1. Open a terminal in this folder and run `build_exe.bat`.
2. Find `PharmacyInventory.exe` in the new `dist\` folder. Copy just that one
   file to wherever it'll actually run from (a folder on the target PC, a USB
   stick, etc).

**First-time setup** (on the PC it'll actually run on):
1. Open a terminal in the folder containing `PharmacyInventory.exe` and run:
   ```
   PharmacyInventory.exe init-admin admin yourpassword
   ```
2. Double-click `PharmacyInventory.exe` from now on — it starts the server
   (no console window) and opens your browser automatically.

The exe creates `pharmacy.db`, `secret_key.txt`, and a `static\` folder next
to itself the first time it runs — that's all your data, and it's everything
you need to back up (see below).

## Option B: Run from source (needs Python installed)

1. Install Python 3.10+.
2. Open a terminal in this folder and run:
   ```
   pip install -r requirements.txt
   ```
3. Create the first admin account:
   ```
   flask --app app init-admin admin yourpassword
   ```
4. Double-click `run.bat`. It starts the server and opens your browser to the app.

## Using it from a phone (same WiFi only, no internet needed)

1. Find this computer's local network address — Windows: open a terminal and run `ipconfig`, look for "IPv4 Address" (e.g. `192.168.1.5`).
2. On your phone, connect to the same WiFi as this computer.
3. Open a browser on the phone and go to `http://<that address>:5000`.

The "Add Photo from Phone" button on the Add Medicine page generates a QR code — scanning it with your phone opens a camera-upload page for that medicine's photo, no typing the address needed. (Note: logging in as admin is required for this button to appear and work.)

## Resetting a password

**Forgot your own password (staff or admin):** log in isn't possible without it — ask an admin to reset it for you (see below).

**Admin resetting a staff member's password:** log in as admin, go to Staff Accounts, click "Reset Password" next to their name, enter a new password.

**Admin locked out (forgot their own password):** there's no in-app recovery — you need terminal access to this computer. Open a terminal in the folder the app runs from and run:
```
PharmacyInventory.exe reset-admin-password admin newpassword
```
(running from source instead: `flask --app app reset-admin-password admin newpassword`)

Replace `admin` with the actual username and `newpassword` with the new password. This only works on an admin account (use the Staff Accounts page above for staff).

## Backing up your data

Everything lives in `pharmacy.db` plus the `static\photos\` folder (uploaded medicine photos) — both sit next to `PharmacyInventory.exe` (or next to `app.py` if running from source). Copy both periodically (e.g. to a USB drive).
