# Azure Deployment Checklist for EOMS

## 1. Upload to GitHub

Upload the **contents** of this folder to your GitHub repository, not the zip file itself.

Make sure GitHub does not contain:

- `.env`
- `.venv` / `venv`
- `runtime`
- `data/rms_browser_profile`
- `bol_files`
- `uploads`
- `diagnostics`

## 2. Azure App Service settings

In Azure Portal:

**App Service > Configuration > Application settings > New application setting**

Add:

```text
SECRET_KEY=<long random key>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<temporary password for first startup>
AZURE_MAPS_KEY=<your Azure Maps key>
SESSION_COOKIE_SECURE=1
DATA_DIR=/home/eoms_data
UPLOAD_DIR=/home/eoms_uploads
BOL_DIR=/home/eoms_bol_files
```

Optional local RMS upload token:

```text
LOCAL_RMS_IMPORT_TOKEN=<long random token>
```

## 3. Startup command

In Azure:

**App Service > Configuration > General settings > Startup Command**

Set:

```bash
bash startup.sh
```

## 4. Deploy from GitHub

Use either:

- Azure Deployment Center connected to GitHub, or
- the included GitHub Actions workflow after updating the app name/secret.

## 5. First login

After first successful startup, log in with:

```text
Username: admin
Password: the ADMIN_PASSWORD you set in Azure
```

Then create your real admin/dispatcher users inside EOMS.

## 6. RMS 403 warning

If RMS returns 403 from Azure, Azure is being blocked by RMS. Use the local RMS normal-browser worker instead of running RMS Auto Grab directly from Azure.
