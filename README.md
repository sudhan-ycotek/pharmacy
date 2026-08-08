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

The "Add Photo from Phone" button on the Add Medicine page generates a QR code — scanning it with your phone opens a camera-upload page for that medicine's photo, no typing the address needed. (Note: logging in as admin is required for this button to appear and work.)

## Backing up your data

Everything is stored in a single file: `pharmacy.db`. Copy it somewhere safe periodically (e.g. a USB drive).
