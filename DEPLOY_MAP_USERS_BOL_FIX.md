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
  - Dispatch route closeout warns if stops are missing rack closeout.
  - Route completion saves a summary of expected racks, collected racks, variance, and completion time.
- System Health check added in Settings.
  - Confirms writable data/upload/BOL folders.
  - Shows whether Playwright is importable.
  - Shows RMS setting status without exposing passwords.
- Duplicate BOL import protection improved.
  - Import now checks BOL plus origin and BOL number to reduce duplicate assignments.
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
`Playwright is not installed`, `Executable doesn't exist`, or `please run playwright install`,
then Azure needs Chromium installed for the App Service worker.

Recommended Azure App Service setting:

```text
PLAYWRIGHT_BROWSERS_PATH=/home/playwright
```

Then use a startup command that installs Chromium before Gunicorn starts:

```bash
python -m playwright install chromium && gunicorn --bind=0.0.0.0 --timeout 600 --workers 2 app:app
```

If this startup command is too slow on every restart, install Chromium once through SSH/Kudu with the same
`PLAYWRIGHT_BROWSERS_PATH=/home/playwright` setting, then return the startup command to normal Gunicorn.

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
