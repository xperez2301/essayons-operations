import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright


def clean(value):
    return "" if value is None else str(value).strip()


def data_dir():
    return Path(os.environ.get("DATA_DIR") or "/app/data")


def worker_log_path():
    return data_dir() / "rms_worker_log.json"


def write_json_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def append_worker_log(status, message, details=None):
    path = worker_log_path()
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            existing = []
    except Exception:
        existing = []

    entry = {
        "id": str(uuid4()),
        "time": datetime.now().isoformat(timespec="seconds"),
        "status": clean(status),
        "message": clean(message),
        "details": details or {},
        "source": "rms_docker_worker",
    }
    existing.append(entry)
    write_json_atomic(path, existing[-250:])
    return entry


def print_json(payload):
    print(json.dumps(payload, default=str), flush=True)


def configure_runtime():
    os.environ.setdefault("RMS_BROWSER", "chromium")
    os.environ.setdefault("RMS_HEADLESS", "true")
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")
    os.environ.setdefault("DATA_DIR", "/app/data")
    os.environ.setdefault("UPLOAD_DIR", "/app/uploads")
    os.environ.setdefault("BOL_DIR", "/app/bol_files")


def api_headers():
    token = clean(os.environ.get("EOMS_WORKER_TOKEN"))
    if not token:
        raise RuntimeError("EOMS_WORKER_TOKEN is required for bridge mode.")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def api_url(path):
    base = clean(os.environ.get("EOMS_API_URL")).rstrip("/")
    if not base:
        raise RuntimeError("EOMS_API_URL is required for bridge mode.")
    if not base.lower().startswith("https://") and clean(os.environ.get("EOMS_ALLOW_HTTP")).lower() not in {"1", "true", "yes"}:
        raise RuntimeError("EOMS_API_URL must use HTTPS.")
    return f"{base}{path}"


def bridge_request(method, path, **kwargs):
    import requests

    response = requests.request(
        method,
        api_url(path),
        headers=api_headers(),
        timeout=int(os.environ.get("EOMS_WORKER_HTTP_TIMEOUT", "30")),
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def chromium_smoke_test():
    configure_runtime()
    import app

    with sync_playwright() as playwright:
        browser = app.launch_chromium_with_repair(playwright, headless=True)
        context = app.new_rms_context(browser)
        page = context.new_page()
        page.goto("about:blank")
        title = page.title()
        context.close()
        browser.close()

    result = {
        "ok": True,
        "status": "CHROMIUM SMOKE TEST COMPLETE",
        "message": "Docker worker launched Chromium headless successfully.",
        "title": title,
    }
    append_worker_log(result["status"], result["message"], result)
    print_json(result)
    return 0


def run_auto_grab_once():
    configure_runtime()
    import app

    max_bols = int(os.environ.get("RMS_WORKER_MAX_BOLS", "0") or 0)
    append_worker_log(
        "RUNNING",
        "RMS Docker worker started Auto Grab.",
        {
            "mode": "manual",
            "max_bols": max_bols,
            "rms_browser": app.rms_browser_choice(),
            "rms_headless": app.rms_headless(True),
        },
    )

    result = app.rms_full_import_with_playwright(
        headless=app.rms_headless(True),
        max_bols=max_bols,
    )
    status = clean(result.get("status")) or ("COMPLETED" if result.get("ok") else "FAILED")
    message = clean(result.get("message")) or "RMS Auto Grab finished."
    append_worker_log(status, message, {"raw_result": result})
    print_json({"ok": bool(result.get("ok")), "result": result})
    return 0 if result.get("ok") else 1


def loop_forever():
    interval = int(os.environ.get("RMS_WORKER_INTERVAL_SECONDS", "10") or 10)
    worker_id = clean(os.environ.get("EOMS_WORKER_ID")) or "rms-docker-worker"
    version = clean(os.environ.get("EOMS_WORKER_VERSION")) or "FT5.2A"
    current_job = None
    last_job = None
    append_worker_log(
        "LOOP STARTED",
        f"RMS Docker worker API loop started. Poll interval {interval} seconds.",
        {"interval_seconds": interval},
    )
    while True:
        bridge_request("POST", "/api/worker/heartbeat", json={
            "worker_id": worker_id,
            "name": "Docker RMS Worker",
            "version": version,
            "state": "BUSY" if current_job else "ONLINE",
            "current_job": current_job,
            "last_job": last_job,
        })
        claimed = bridge_request(
            "GET",
            f"/api/worker/jobs/next?worker_id={worker_id}",
        ).get("job")
        if claimed:
            current_job = claimed.get("id")
            bridge_request("POST", "/api/worker/heartbeat", json={
                "worker_id": worker_id,
                "name": "Docker RMS Worker",
                "version": version,
                "state": "BUSY",
                "current_job": current_job,
                "last_job": last_job,
            })
            try:
                configure_runtime()
                import app
                max_bols = int((claimed.get("payload") or {}).get("max_bols") or os.environ.get("RMS_WORKER_MAX_BOLS", "0"))
                result = app.rms_full_import_with_playwright(
                    headless=app.rms_headless(True),
                    max_bols=max_bols,
                )
                completion = {
                    "worker_id": worker_id,
                    "ok": bool(result.get("ok")),
                    "result": result,
                    "error": None if result.get("ok") else clean(result.get("message")),
                }
            except Exception as exc:
                completion = {
                    "worker_id": worker_id,
                    "ok": False,
                    "result": None,
                    "error": str(exc)[:2000],
                }
            bridge_request("POST", f"/api/worker/jobs/{current_job}/complete", json=completion)
            last_job = current_job
            current_job = None
        time.sleep(interval)


def main():
    mode = clean(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("RMS_WORKER_MODE") or "run").lower()
    try:
        if mode in {"smoke", "smoke-test", "chromium-smoke"}:
            return chromium_smoke_test()
        if mode in {"loop", "daemon"}:
            return loop_forever()
        if mode in {"run", "once", "manual", "auto-grab", "autograb"}:
            return run_auto_grab_once()
        print_json({"ok": False, "status": "INVALID MODE", "message": f"Unknown RMS worker mode: {mode}"})
        return 2
    except Exception as exc:
        details = {
            "error": str(exc)[:1200],
            "traceback": traceback.format_exc()[-4000:],
        }
        append_worker_log("FAILED", f"RMS Docker worker failed: {str(exc)[:300]}", details)
        print_json({"ok": False, "status": "FAILED", "message": str(exc), "details": details})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
