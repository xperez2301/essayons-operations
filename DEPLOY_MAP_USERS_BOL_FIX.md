# EOMS reliability upgrade: map pins, archive, closeout, users, drivers, and BOL notes

## Included code changes

- Map pins now follow this due-date color rule:
  - Red: overdue or 4 days or less remaining.
  - Amber: 5 through 7 days remaining.
  - Green: more than 7 days remaining, or no due date captured.
- User Management now has a Delete button for each user.
- Driver Management now has a Delete Driver button for driver accounts.
- Archive/History page added at `/archive`.
  - Shows completed BOLs and completed routes.
  - Search by BOL, route, driver, store, city, and completed date range.
  - Keeps saved/print/live BOL links available for completed work.
- Admin backup export added at `/api/export/data`.
  - Downloads a ZIP of the core JSON data files.
  - The button appears on the Archive page for admins.
- Closeout validation added.
  - Drivers must enter collected rack count before completing a stop.
  - Drivers can enter collected PCS count during stop completion.
  - If PCS is left blank, the system estimates PCS from collected racks.
  - Dispatch/Admin can edit collected racks and PCS later from the Archive page.
  - Dispatch route closeout warns if stops are missing rack closeout.
  - Route completion saves a summary of expected racks, collected racks, expected PCS, collected PCS, variance, and completion time.
- System Health check added in Settings.
  - Confirms writable data/upload/BOL folders.
  - Shows whether Playwright is importable.
  - Shows RMS setting status without exposing passwords.
- Duplicate BOL import protection improved.
  - Import now checks BOL plus origin and BOL number to reduce duplicate assignments.
- Dispatch Map display controls added in Settings.
  - Default map view now starts as Satellite.
  - Admin can switch the default map view to Satellite, Hybrid, Road Map, or Terrain.
  - Admin can set default map zoom.
  - Admin can choose whether the dispatch board opens by default.
  - Admin can set dispatch board refresh seconds.
  - Admin can adjust red/amber/green due-date pin thresholds without changing code.
- Operations Dashboard includes an Admin-only Auto Grab BOLs button.
  - It calls the RMS full import engine directly from the dashboard.
  - It reports found/imported/updated/failed results and refreshes the page after success.
- It now detects login-page, missing-endpoint, and Azure/server HTML responses instead of showing `Unexpected token '<'`.
- The server endpoint returns a JSON error even if the RMS automation raises an exception.
- Playwright browser self-repair added.
  - If Chromium is missing, EOMS attempts `python -m playwright install chromium` automatically.
  - If Azure reports missing Linux browser dependencies, EOMS attempts `python -m playwright install-deps chromium` automatically, then retries Chromium.
  - It installs into `PLAYWRIGHT_BROWSERS_PATH`, recommended as `/home/playwright` on Azure.
  - The first Auto Grab after deployment may take several minutes while Chromium and the Linux dependencies install.
- RMS full import pagination is more resilient.
  - BOL list links are captured as a single browser-side snapshot, avoiding `Locator.all: Execution context was destroyed` when RMS refreshes or navigates during pagination.
- RMS login automation is more tolerant of slow or changed login pages.
  - Login fields now wait longer, use visible-field detection, and report the RMS page URL/title/body snippet if the login form does not appear.
- Dashboard Auto Grab now reports what actually happened.
  - Existing BOLs are updated instead of skipped, so re-grabbing RMS refreshes saved BOL data.
  - The dashboard shows scanned, imported, updated, skipped, need-review, failed, and error details.
  - If RMS loads but no BOL links are found, the app saves diagnostics under `diagnostics/` and reports the RMS page summary.
- RMS BOL discovery matches the live RMS URL pattern.
  - Login URL: `https://rms.reusability.com/login`
  - BOL list URL: `https://rms.reusability.com/bills-of-lading`
  - Printable URL pattern: `https://rms.reusability.com/bills-of-lading/<BOL>/print`
  - Auto Grab now detects BOL numbers from anchor text, BOL link URLs, and table row text.
- RMS printable BOL pages are saved as PDFs.
  - Auto Grab, RMS Queue import, and Repair BOL now open the printable URL and save it as a `.pdf` under `BOL_DIR/Imported` or `BOL_DIR/Need_Review`.
  - If Chromium cannot export PDF for any reason, EOMS falls back to the previous HTML snapshot instead of losing the BOL.
- Delete safeguards:
  - An admin cannot delete their own currently logged-in user.
  - The system will not delete the last active admin account.
- Deleting a driver removes the driver login/contact record. Existing route history remains available.

## Where completed history lives

- Store/BOL records are saved in `DATA_DIR/stores.json`.
- Route records are saved in `DATA_DIR/routes.json`.
- Completed BOL PDF files are moved under `BOL_DIR/Completed/YYYY/MM_Month/`.
- Admin/user actions are recorded in `DATA_DIR/audit_log.json`.
- On Azure, use the `/archive` page to search history and the `Download Backup` button to export the core history files.

## Azure settings required for BOL auto-grab persistence

Add these App Service environment variables:

```text
DATA_DIR=/home/data
BOL_DIR=/home/bol_files
UPLOAD_DIR=/home/uploads
```

Keep the existing security settings:

```text
SECRET_KEY=<long random value>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong initial password>
SESSION_COOKIE_SECURE=1
```

## If RMS/BOL auto-grab still does not work

The RMS auto-grabber uses Playwright/Chromium. If the portal shows an error like
`Playwright is not installed`, `Executable doesn't exist`, `please run playwright install`,
or `Host system is missing dependencies`, then Azure needs Chromium and its Linux
shared libraries installed for the App Service worker.

Recommended Azure App Service setting:

```text
PLAYWRIGHT_BROWSERS_PATH=/home/playwright
```

Then use a startup command that installs Chromium and its Linux dependencies before Gunicorn starts:

```bash
python -m playwright install --with-deps chromium && gunicorn --bind=0.0.0.0 --timeout 600 --workers 2 app:app
```

If this startup command is too slow on every restart, install Chromium and dependencies once through
SSH/Kudu with the same `PLAYWRIGHT_BROWSERS_PATH=/home/playwright` setting:

```bash
python -m playwright install-deps chromium
python -m playwright install chromium
```

Then return the startup command to normal Gunicorn.

## What non-admin users can see

- Admin:
  - Full portal access.
  - Users, Settings, RMS Sync, RMS Import, RMS Queue.
  - Financial metrics.
- Operations Manager:
  - Dispatch/dashboard/route views for allowed assigned cities.
  - Financial metrics.
  - No Users, Settings, or RMS admin pages.
- Dispatcher:
  - Dispatch/dashboard/route views for allowed assigned cities.
  - Can build/dispatch routes.
  - No financial metrics.
  - No Users, Settings, or RMS admin pages.
- Driver:
  - Redirected to Driver view.
  - Sees only routes/stops assigned to that driver account.
  - Cannot access dashboard, dispatch map, users, settings, or RMS pages.

City filtering is controlled by the assigned cities selected on the Users page.
