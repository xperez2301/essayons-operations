"""Run RMS Auto Grab locally in the operator's visible Edge session."""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
LOG_PATH = Path(os.environ.get("EOMS_LOCAL_WORKER_LOG") or BASE_DIR / "diagnostics" / "eoms_local_worker.log")
BOL_DATA_PATH = Path(os.environ.get("EOMS_BOL_DATA_FILE") or BASE_DIR / "bol_data.json")
EDGE_PROFILE_PATH = Path(
    os.environ.get("EOMS_EDGE_PROFILE_DIR")
    or BASE_DIR / "runtime" / "rms_user_edge_debug_profile"
)
RMS_URL = "https://rms.reusability.com/bills-of-lading"


def configure_logging():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
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


def cdp_endpoint():
    return clean(os.environ.get("RMS_CDP_ENDPOINT") or "http://127.0.0.1:9223").rstrip("/")


def cdp_is_ready():
    try:
        response = requests.get(f"{cdp_endpoint()}/json/version", timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False


def edge_executable():
    configured = clean(os.environ.get("EOMS_EDGE_PATH"))
    candidates = [
        Path(configured) if configured else None,
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise RuntimeError(
        "Microsoft Edge was not found. Set EOMS_EDGE_PATH to msedge.exe."
    )


def ensure_dedicated_edge():
    if cdp_is_ready():
        logging.info("Dedicated EOMS Edge is already available at %s.", cdp_endpoint())
        return None

    EDGE_PROFILE_PATH.mkdir(parents=True, exist_ok=True)
    command = [
        str(edge_executable()),
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={cdp_endpoint().rsplit(':', 1)[-1]}",
        "--remote-allow-origins=*",
        f"--user-data-dir={EDGE_PROFILE_PATH}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=msEdgeStartupBoost",
        RMS_URL,
    ]
    logging.info("Launching dedicated visible EOMS Edge.")
    process = subprocess.Popen(
        command,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    timeout = int(os.environ.get("EOMS_EDGE_START_TIMEOUT_SECONDS", "30"))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cdp_is_ready():
            logging.info("Dedicated EOMS Edge CDP is ready.")
            return process
        if process.poll() is not None:
            break
        time.sleep(0.5)

    try:
        process.terminate()
    except Exception:
        pass
    raise RuntimeError(
        f"Microsoft Edge did not make CDP available at {cdp_endpoint()} within {timeout} seconds."
    )


def close_dedicated_edge(process=None):
    """Close only the Edge instance bound to the dedicated EOMS CDP port."""
    if cdp_is_ready():
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(cdp_endpoint())
                browser.close()
            logging.info("Closed the dedicated EOMS Edge browser through CDP.")
        except Exception as exc:
            logging.warning("Could not close dedicated Edge through CDP: %s", exc)

    if process is not None and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=10)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception as exc:
                logging.warning("Could not terminate the dedicated Edge process: %s", exc)

    deadline = time.monotonic() + 10
    while cdp_is_ready() and time.monotonic() < deadline:
        time.sleep(0.25)
    if cdp_is_ready():
        logging.error("Dedicated EOMS Edge is still listening at %s.", cdp_endpoint())
        return False
    return True


def run_auto_grab():
    # Manual mode keeps the existing scraper from closing the CDP browser
    # before this worker has synchronized its final result.
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
    edge_process = None
    report_posted = False
    try:
        try:
            edge_process = ensure_dedicated_edge()
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
            report_posted = True
            logging.info("Final sync result posted to EOMS.")
        except Exception:
            logging.exception("Unable to post final sync result to EOMS.")
    finally:
        edge_closed = close_dedicated_edge(edge_process)
        logging.info("Dedicated EOMS Edge cleanup complete: %s.", "yes" if edge_closed else "no")

    logging.info("Local visible RMS worker finished: %s", summary.get("status") or "UNKNOWN")
    return 0 if summary.get("ok") and report_posted and edge_closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
