# Essayons Operations authentication fix

## Root cause

The repository's `main` branch has no authentication middleware. The login
implementation exists on `production`, so a host configured to deploy `main`
publishes the operational portal without a login requirement.

This bundle is based on the protected `production` application and adds
fail-closed authentication configuration and regression tests.

## Required application settings

Set these in the hosting environment before deploying:

- `SECRET_KEY`: a new random value of at least 32 bytes. Do not reuse the old
  fallback value. Generating a new value also invalidates existing sessions.
- `ADMIN_USERNAME`: the initial administrator username (usually `admin`).
- `ADMIN_PASSWORD`: a new strong initial administrator password.
- `SESSION_COOKIE_SECURE=1`: keep this enabled on the HTTPS production site.
- `DATA_DIR=/home/data`, `BOL_DIR=/home/bol_files`, and
  `UPLOAD_DIR=/home/uploads` on Azure App Service when persistent storage is
  required.

Generate `SECRET_KEY` locally with:

```powershell
py -c "import secrets; print(secrets.token_hex(32))"
```

## Deployment

1. Back up the persistent data directory.
2. Configure the required settings above.
3. Deploy this bundle, or merge the corresponding protected `production`
   source into the branch your host actually deploys.
4. Restart the application.
5. In a private/incognito browser, verify `/dashboard`, `/dispatch-map`,
   `/driver`, and `/api/routes` cannot be accessed anonymously.
6. Rotate the administrator password and remove `ADMIN_PASSWORD` from the
   environment after confirming the seeded administrator account works.

Do not deploy the original archive's `.git`, `data`, `uploads`, `bol_files`, or
`diagnostics` directories. They contain operational material and are omitted
from this clean bundle.

## Regression tests

After installing `requirements.txt`, run:

```powershell
$env:SECRET_KEY='test-only-secret-key-with-at-least-32-characters'
$env:ADMIN_PASSWORD='test-only-admin-password'
$env:SESSION_COOKIE_SECURE='0'
py tests/test_auth.py
```
