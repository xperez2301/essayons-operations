"""Run RMS Auto Grab locally in the operator's visible Edge session."""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
LOG_PATH = Path(os.environ.get("EOMS_LOCAL_WORKER_LOG") or BASE_DIR / "diagnostics" / "eoms_local_worker.log")
BOL_DATA_PATH = Path(os.environ.get("EOMS_BOL_DATA_FILE") or BASE_DIR / "bol_data.json")


def configure_logging():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
        ],
    )


def clean(value):
    return "" if value is None else str(value).strip()


def atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(temporary, path)


def summarize_result(result):
    errors = result.get("errors") or []
    if not isinstance(errors, list):
        errors = [clean(errors)] if errors else []
    return {
        "ok": bool(result.get("ok")),
        "status": clean(result.get("status")),
        "bols_found": int(result.get("found", result.get("bol_count", 0)) or 0),
        "bols_new": int(result.get("imported", result.get("added", 0)) or 0),
        "stores_checked": int(result.get("stores_checked", result.get("found", result.get("bol_count", 0))) or 0),
        "imported": int(result.get("imported", 0) or 0),
        "updated": int(result.get("updated", 0) or 0),
        "errors": errors,
        "error_message": clean(result.get("message")) if not result.get("ok") else "",
        "message": clean(result.get("message")),
    }


def run_auto_grab():
    # These settings make the existing scraper attach to the operator-owned
    # Edge tab. In manual mode app.close_rms_browser() intentionally does
    # nothing, so the visible browser remains open after the run.
    os.environ["RMS_BROWSER"] = "cdp"
    os.environ["RMS_HEADLESS"] = "0"
    os.environ["RMS_MANUAL_LOGIN"] = "1"
    os.environ.setdefault("RMS_CDP_ENDPOINT", "http://127.0.0.1:9223")

    import app

    logging.info("Attaching RMS Auto Grab to visible Edge at %s", os.environ["RMS_CDP_ENDPOINT"])
    return app.rms_full_import_with_playwright(headless=False, max_bols=0)


def post_sync_result(timestamp, result):
    base_url = clean(os.environ.get("EOMS_BASE_URL") or os.environ.get("AZURE_EOMS_URL")).rstrip("/")
    token = clean(os.environ.get("EOMS_WORKER_TOKEN"))
    if not base_url:
        raise RuntimeError("EOMS_BASE_URL is required.")
    if not token:
        raise RuntimeError("EOMS_WORKER_TOKEN is required.")
    response = requests.post(
        f"{base_url}/api/sync-result",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"timestamp": timestamp, "source": "eoms-local-worker", "result": result},
        timeout=int(os.environ.get("EOMS_WORKER_HTTP_TIMEOUT", "30")),
    )
    response.raise_for_status()
    return response.json()


def main():
    configure_logging()
    timestamp = datetime.now().isoformat(timespec="seconds")
    logging.info("Local visible RMS worker started.")
    try:
        raw_result = run_auto_grab()
        summary = summarize_result(raw_result)
    except Exception as exc:
        logging.exception("RMS Auto Grab failed.")
        summary = summarize_result({
            "ok": False,
            "status": "FAILED",
            "message": str(exc),
            "errors": [str(exc)],
        })

    atomic_write_json(BOL_DATA_PATH, {"last_run": timestamp, "last_result": summary})
    logging.info("Updated %s using atomic UTF-8 write.", BOL_DATA_PATH)

    try:
        post_sync_result(timestamp, summary)
        logging.info("Final sync result posted to EOMS.")
    except Exception:
        logging.exception("Unable to post final sync result to EOMS.")
        return 1

    logging.info("Local visible RMS worker finished: %s", summary.get("status") or "UNKNOWN")
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
