# Local RMS Worker

RMS blocks Azure/server browsers before the login form with a 403, so EOMS uses one system with split responsibilities:

- Azure App Service runs the dashboard, iPad portal, users, maps, and import receiver.
- The office PC runs RMS Auto Grab with a normal Chrome/Edge browser session.
- The office PC uploads the imported BOL PDFs/CSV/XLSX files to Azure through `POST /api/local-rms/import`.

## Azure app settings

Set these in App Service > Settings > Environment variables:

```text
SECRET_KEY=<long random value>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong password>
AZURE_MAPS_KEY=<Azure Maps key>
SESSION_COOKIE_SECURE=1
RMS_HEADLESS=1
RMS_MANUAL_LOGIN=0
LOCAL_RMS_IMPORT_TOKEN=<long random token>
```

## Local `.env`

Copy `.env.example` to `.env` on the office PC and set:

```text
SECRET_KEY=<local secret>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<local admin password>
AZURE_MAPS_KEY=<same key>
SESSION_COOKIE_SECURE=0
RMS_HEADLESS=0
RMS_MANUAL_LOGIN=1
RMS_BROWSER=chrome
LOCAL_RMS_IMPORT_TOKEN=<same token as Azure>
AZURE_EOMS_URL=https://eoms-dispatch-d5dcabencherf2ft.centralus-01.azurewebsites.net
```

## Daily schedule

Double-click `INSTALL_LOCAL_RMS_SYNC_TASK.bat` on the office PC. It creates a Windows scheduled task named `EOMS Local RMS Sync` that runs daily at 06:00.

The task runs `tools/local_rms_upload.ps1`, which calls local EOMS Auto Grab, collects new PDF/XLSX/CSV files, uploads them to Azure, and writes `diagnostics/local_rms_upload.log`.