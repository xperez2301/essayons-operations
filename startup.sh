#!/usr/bin/env bash
set -e

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/home/playwright}"
export RMS_BROWSER="${RMS_BROWSER:-chromium}"
export RMS_HEADLESS="${RMS_HEADLESS:-true}"

echo "[EOMS Startup] IS_AZURE=$([ -n "${WEBSITE_SITE_NAME:-}" ] && echo true || echo false)"
echo "[EOMS Startup] RMS_BROWSER=${RMS_BROWSER}"
echo "[EOMS Startup] RMS_HEADLESS=${RMS_HEADLESS}"
echo "[EOMS Startup] PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH}"
echo "[EOMS Startup] current_user=$(id -un 2>/dev/null || whoami 2>/dev/null || echo unknown)"
echo "[EOMS Startup] /home/eoms_data exists: $([ -d /home/eoms_data ] && echo yes || echo no)"

mkdir -p "${PLAYWRIGHT_BROWSERS_PATH}" || true
echo "[EOMS Startup] /home/playwright exists: $([ -d /home/playwright ] && echo yes || echo no)"

echo "[EOMS Startup] Installing Playwright Chromium..."
python -m playwright install chromium

echo "[EOMS Startup] Installing Playwright Chromium Linux dependencies if supported..."
python -m playwright install-deps chromium || echo "[EOMS Startup] playwright install-deps chromium skipped or unsupported on this host."

echo "[EOMS Startup] Playwright Chromium executable path:"
python - <<'PY' || echo "[EOMS Startup] Chromium executable path unavailable."
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    print(p.chromium.executable_path)
PY

python -m gunicorn --bind=0.0.0.0:${PORT:-8000} --timeout 600 --workers ${WEB_CONCURRENCY:-2} app:app
