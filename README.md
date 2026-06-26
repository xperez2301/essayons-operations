# EOMS - Essayons Operations Management System

Deployment-ready EOMS package for GitHub -> Azure App Service.

## What belongs in GitHub

Commit the source code only:

- `app.py`
- `templates/`
- `static/`
- `requirements.txt`
- `runtime.txt`
- `startup.sh` / `startup.txt`
- `.github/workflows/`
- `.env.example`
- `data/*.example.json`
- placeholder files such as `data/.gitkeep`, `uploads/.gitkeep`, `diagnostics/.gitkeep`

Do **not** commit live operational data, browser profiles, BOL PDFs, virtual environments, secrets, or logs.

## Required Azure App Service settings

In Azure Portal -> App Service -> Settings -> Environment variables, add:

```text
SECRET_KEY=<long random secret>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<your first admin password>
DATA_DIR=/home/data
BOL_DIR=/home/bol_files
UPLOAD_DIR=/home/uploads
AZURE_MAPS_KEY=<your Azure Maps key>
SESSION_COOKIE_SECURE=1
```

Generate `SECRET_KEY` locally:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

After the first admin account is created, keep `SECRET_KEY` the same. Changing it signs everyone out.

## Azure startup command

Use this startup command in Azure App Service:

```text
bash startup.sh
```

Or use the included `startup.txt` as a note/reference.

## GitHub Actions deployment

This package includes `.github/workflows/production_eoms-dispatch.yml`.

Before it works, add your Azure publish profile as a GitHub repository secret. The workflow currently references:

```text
AZUREAPPSERVICE_PUBLISHPROFILE_7B58759A34D04AFB831B18678A70C081
```

If your secret has a different name, update the workflow file.

## RMS Auto Grab note

RMS may block Azure server IPs or automation browsers with HTTP 403. This build keeps RMS automation code in EOMS, but the safest setup is:

```text
Azure = EOMS dashboard/web app/database storage
Local PC = RMS Auto Grab normal Chrome browser worker
```

For local RMS normal-browser mode:

```powershell
python -m pip install -r requirements.txt
python -m playwright install chrome
copy .env.example .env
# edit .env with SECRET_KEY, ADMIN_PASSWORD, Azure Maps key, etc.
python app.py
```

Then log into RMS in the visible Chrome window and go to **Orders & BOLs -> Bills of Lading** before running Auto Grab.

## Local run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open: `http://127.0.0.1:5000`

