# Essayons Operations (EOMS)

Flask dispatch + RMS/BOL operations platform for 4 US & Company / Essayons Bax.

This is the hardened, deploy-ready version. It keeps all of your existing
features (dispatch map, route builder, RMS import/queue/sync, BOL handling,
driver portal, user management with role + city permissions) and fixes the
things that would have bitten you in production.

---

## What changed in this version

- **Passwords are now hashed** (werkzeug), not stored in plaintext. Any old
  plaintext password is verified once on next login and then upgraded to a hash
  automatically — nobody gets locked out.
- **Secrets come from environment variables**, not from files in the repo. The
  RMS username/password, Google Maps key, admin password, and Flask secret key
  are all read from the environment (Azure app settings or a local `.env`).
- **No secrets or live data in git.** `.gitignore` keeps `.env`,
  `data/settings.json`, `data/users.json`, `bol_files/`, `uploads/`, and
  `diagnostics/` out of the repository.
- **Atomic JSON writes** — a crash mid-save can no longer corrupt a data file.
- **Survives redeploys on Azure.** Point `DATA_DIR`/`BOL_DIR` at `/home/...`
  (persistent) so deploying new code doesn't wipe your stores, routes, or BOLs.
- **Won't crash if Playwright is missing.** RMS automation just becomes
  disabled with a clear message instead of taking the whole site down.
- Production-safe startup (gunicorn, debug off by default).

> ⚠️ **Do this first — rotate the old secrets.** The previous version had your
> real RMS password and a Google Maps API key committed in `data/settings.json`,
> and an admin password in `data/users.json`. Treat all of those as compromised:
> change the RMS password, regenerate the Maps key (and restrict it by HTTP
> referrer in Google Cloud), and set a new `ADMIN_PASSWORD`. The new version
> never stores those in the repo.

---

## 1. Open it in VS Code and run locally

```bash
# from the folder that contains this README
code .                      # opens VS Code here (or File > Open Folder)
```

In the VS Code terminal (`Ctrl+`` `):

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt

# create your local secrets file
copy .env.example .env       # Windows  (use: cp .env.example .env on mac/linux)
```

Open `.env` and fill in at least `SECRET_KEY` and `ADMIN_PASSWORD`. Generate a
secret key with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Then run it:

```bash
python app.py
```

Open http://localhost:5000 and log in with `admin` / the `ADMIN_PASSWORD` you set.

> The RMS scraping features also need a browser engine. If you want them locally:
> `playwright install chromium`.

---

## 2. Put it on GitHub

```bash
git init
git add .
git commit -m "Hardened, deploy-ready EOMS"
git branch -M main
git remote add origin https://github.com/<your-username>/essayons-operations.git
git push -u origin main
```

Check on github.com that `.env`, `data/settings.json`, and `data/users.json`
are **not** there. They shouldn't be — `.gitignore` excludes them.

---

## 3. Deploy to Azure App Service

You only do steps A–F once. After that, every `git push` to `main`
auto-deploys via GitHub Actions.

### A. Create the Web App (Azure CLI)

```bash
az login

az group create --name essayons-rg --location southcentralus

az appservice plan create \
  --name essayons-plan --resource-group essayons-rg --is-linux --sku B1

az webapp create \
  --name essayons-eoms \
  --resource-group essayons-rg \
  --plan essayons-plan \
  --runtime "PYTHON:3.11"
```

(`essayons-eoms` must be globally unique — pick your own; that name becomes
`https://essayons-eoms.azurewebsites.net`.)

### B. Set the startup command

```bash
az webapp config set \
  --resource-group essayons-rg --name essayons-eoms \
  --startup-file "gunicorn --bind=0.0.0.0 --timeout 600 --workers 2 app:app"
```

### C. Set your environment variables (these replace the committed secrets)

```bash
az webapp config appsettings set \
  --resource-group essayons-rg --name essayons-eoms \
  --settings \
    SECRET_KEY="<paste a token_hex(32) value>" \
    ADMIN_USERNAME="admin" \
    ADMIN_PASSWORD="<a strong password>" \
    RMS_USERNAME="<your rms login>" \
    RMS_PASSWORD="<your new rms password>" \
    GOOGLE_MAPS_API_KEY="<your restricted maps key>" \
    DATA_DIR="/home/data" \
    BOL_DIR="/home/bol_files" \
    UPLOAD_DIR="/home/uploads"
```

`DATA_DIR=/home/...` is important: `/home` persists across restarts and
deployments, so your live data isn't wiped when new code ships.

### D. Get the publish profile (credential GitHub Actions uses)

```bash
az webapp deployment list-publishing-profiles \
  --resource-group essayons-rg --name essayons-eoms --xml
```

Copy the **entire** XML output.

### E. Add it as a GitHub secret

In your repo on GitHub: **Settings → Secrets and variables → Actions → New
repository secret**.
- Name: `AZURE_WEBAPP_PUBLISH_PROFILE`
- Value: the XML you copied.

### F. Point the workflow at your app

Edit `.github/workflows/azure-deploy.yml` and change:

```yaml
AZURE_WEBAPP_NAME: REPLACE-WITH-YOUR-APP-NAME
```

to your real app name (e.g. `essayons-eoms`), then commit and push:

```bash
git add .github/workflows/azure-deploy.yml
git commit -m "Set Azure app name"
git push
```

Watch the **Actions** tab on GitHub. When it goes green, your site is live at
`https://<your-app-name>.azurewebsites.net`.

---

## Logs / troubleshooting

```bash
az webapp log tail --resource-group essayons-rg --name essayons-eoms
```

- **Site won't start** → check the startup command (step B) and that
  `requirements.txt` installed cleanly in the Actions log.
- **RMS buttons error out** → Playwright's browser isn't installed on the
  worker. RMS automation needs `playwright install chromium` to run in the
  container; the rest of the app is unaffected. (For heavy/reliable scraping,
  the better long-term move is a separate worker or a container image — see
  notes below.)
- **Data disappeared after a deploy** → you didn't set `DATA_DIR=/home/data`
  (step C).

---

## Known limitations / good next steps

These weren't changed to avoid disrupting your working app, but are worth doing:

1. **JSON files as the database.** Fine for one or two simultaneous users, but
   it doesn't lock and won't scale to many concurrent dispatchers. Moving
   `stores`/`routes`/`users` to SQLite (on the `/home` volume) or Azure Postgres
   is the natural upgrade.
2. **Playwright/RMS scraping inside web requests** is slow and fragile on App
   Service. A background worker or queue is more robust than running Chromium
   inside an HTTP handler.
3. **No CSRF tokens** on the POST forms. Low risk for an internal, login-gated
   tool, but `Flask-WTF` would close it.

Happy to tackle any of these next.
