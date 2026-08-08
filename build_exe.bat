@echo off
cd /d %~dp0
echo Installing build dependencies...
pip install -r requirements.txt pyinstaller
echo.
echo Building PharmacyInventory.exe...
pyinstaller --onefile --noconsole --name PharmacyInventory ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --add-data "schema.sql;." ^
  app.py
echo.
echo Done. Find PharmacyInventory.exe in the dist\ folder.
echo Copy that one file anywhere you like on this PC — it creates its own
echo pharmacy.db, secret_key.txt, and static\ folder next to itself the first
echo time it runs.
pause
