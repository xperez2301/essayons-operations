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
    interval = int(os.environ.get("RMS_WORKER_INTERVAL_SECONDS", "300") or 300)
    append_worker_log(
        "LOOP STARTED",
        f"RMS Docker worker loop started. Interval {interval} seconds.",
        {"interval_seconds": interval},
    )
    while True:
        code = run_auto_grab_once()
        if code != 0 and clean(os.environ.get("RMS_WORKER_STOP_ON_ERROR")).lower() in {"1", "true", "yes", "on"}:
            return code
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
