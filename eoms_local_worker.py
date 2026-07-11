"""Run RMS Auto Grab locally in the operator's visible Edge session."""

import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
LOG_PATH = Path(os.environ.get("EOMS_LOCAL_WORKER_LOG") or BASE_DIR / "diagnostics" / "eoms_local_worker.log")
BOL_DATA_PATH = Path(os.environ.get("EOMS_BOL_DATA_FILE") or BASE_DIR / "bol_data.json")
SYNC_QUEUE_PATH = Path(os.environ.get("EOMS_LOCAL_SYNC_QUEUE_FILE") or BASE_DIR / "diagnostics" / "rms_sync_queue.json")
SYNC_HISTORY_PATH = Path(os.environ.get("EOMS_LOCAL_SYNC_HISTORY_FILE") or BASE_DIR / "diagnostics" / "rms_sync_history.json")
EDGE_PROFILE_PATH = Path(
    os.environ.get("EOMS_EDGE_PROFILE_DIR")
    or BASE_DIR / "runtime" / "rms_user_edge_debug_profile"
)
RMS_URL = "https://rms.reusability.com/bills-of-lading"
WORKER_VERSION = os.environ.get("EOMS_LOCAL_WORKER_VERSION") or "FT6.1"
ACTIVE_SYNC_STATUSES = {"Pending", "Failed"}
PERSISTED_SYNC_STATUSES = {"Pending", "Uploading", "Failed"}


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


def normalize_bol_number(value):
    raw = clean(value).upper()
    if raw.startswith("BOL"):
        raw = raw[3:]
    return re.sub(r"[^A-Z0-9]", "", raw)


def atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(temporary, path)


def read_json_file(path, default):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, type(default)) else default
    except Exception:
        return default


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sync_operator():
    return clean(os.environ.get("EOMS_OPERATOR") or os.environ.get("USERNAME") or os.environ.get("USER") or "local-operator")


def load_sync_queue():
    queue = read_json_file(SYNC_QUEUE_PATH, {})
    changed = False
    for entry in queue.values():
        if clean(entry.get("status")) == "Uploading":
            entry["status"] = "Pending"
            entry["failure_reason"] = "Worker stopped before upload confirmation; retry pending."
            changed = True
    if changed:
        save_sync_queue(queue)
    return queue


def save_sync_queue(queue):
    active = {
        bol: entry
        for bol, entry in (queue or {}).items()
        if clean(entry.get("status")) in PERSISTED_SYNC_STATUSES
    }
    atomic_write_json(SYNC_QUEUE_PATH, active)
    return active


def load_sync_history():
    return read_json_file(SYNC_HISTORY_PATH, [])


def save_sync_history(history):
    atomic_write_json(SYNC_HISTORY_PATH, (history or [])[-250:])


def history_confirmed_bols(history=None):
    confirmed = set()
    for run in history or load_sync_history():
        for item in run.get("bols") or []:
            if clean(item.get("status")) in {"Imported", "Already Exists"}:
                normalized = normalize_bol_number(item.get("normalized_bol") or item.get("bol"))
                if normalized:
                    confirmed.add(normalized)
    return confirmed


def merge_imported_pdfs_into_queue(imported_pdfs):
    queue = load_sync_queue()
    historical_confirmed = history_confirmed_bols()
    now = utc_now_iso()
    duplicates_skipped = []

    for bol, info in (imported_pdfs or {}).items():
        normalized = normalize_bol_number(bol)
        if not normalized:
            continue
        if normalized in historical_confirmed:
            duplicates_skipped.append(normalized)
            continue

        current = queue.get(normalized) if isinstance(queue.get(normalized), dict) else {}
        if clean(current.get("status")) not in {"Uploading"}:
            queue[normalized] = {
                **current,
                **(info or {}),
                "bol": clean(info.get("source_bol") if isinstance(info, dict) else "") or clean(bol),
                "normalized_bol": normalized,
                "status": clean(current.get("status")) if clean(current.get("status")) in ACTIVE_SYNC_STATUSES else "Pending",
                "failure_reason": clean(current.get("failure_reason")),
                "queued_at": clean(current.get("queued_at")) or now,
                "updated_at": now,
            }

    save_sync_queue(queue)
    return load_sync_queue(), duplicates_skipped


def active_upload_entries(queue):
    entries = {}
    for bol, entry in (queue or {}).items():
        if clean(entry.get("status")) in ACTIVE_SYNC_STATUSES:
            entries[bol] = entry
    return entries


def mark_queue_status(queue, bols, status, reason=""):
    now = utc_now_iso()
    for bol in bols or []:
        normalized = normalize_bol_number(bol)
        if normalized in queue:
            queue[normalized]["status"] = status
            queue[normalized]["updated_at"] = now
            if reason:
                queue[normalized]["failure_reason"] = reason
            elif status in {"Pending", "Uploading", "Imported", "Already Exists"}:
                queue[normalized]["failure_reason"] = ""
    save_sync_queue(queue)
    return load_sync_queue()


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
    base_url = worker_base_url()
    token, auth_mode = worker_auth_token()
    if not base_url:
        raise RuntimeError("EOMS_BASE_URL is required.")
    if not token:
        raise RuntimeError("EOMS_WORKER_TOKEN is required for final sync callbacks.")
    target_url = f"{base_url}/api/sync-result"
    logging.info("Posting final RMS sync result to %s using %s authentication.", target_url, auth_mode)
    response = requests.post(
        target_url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"timestamp": timestamp, "source": "eoms-local-worker", "result": result},
        timeout=int(os.environ.get("EOMS_WORKER_HTTP_TIMEOUT", "30")),
    )
    response.raise_for_status()
    return response.json()


def worker_base_url():
    return clean(os.environ.get("EOMS_BASE_URL") or os.environ.get("AZURE_EOMS_URL")).rstrip("/")


def worker_auth_token():
    token = clean(os.environ.get("EOMS_WORKER_TOKEN"))
    if token:
        return token, "EOMS_WORKER_TOKEN"
    legacy_token = clean(os.environ.get("LOCAL_RMS_IMPORT_TOKEN"))
    if legacy_token:
        return legacy_token, "LOCAL_RMS_IMPORT_TOKEN legacy fallback"
    return "", "missing worker token"


def _upload_batch_to_azure(base_url, token, batch):
    """Upload a single batch (dict of bol -> {pdf_path, due_date, assigned_date})
    in one multipart request. Raises on any HTTP-level failure."""
    bol_data_sidecar = {}
    for bol, info in batch.items():
        normalized = normalize_bol_number(bol)
        bol_data_sidecar[normalized or clean(bol)] = {
            "due_date": info.get("due_date", ""),
            "assigned_date": info.get("assigned_date", ""),
        }

    open_files = []
    try:
        files = []
        for bol, info in batch.items():
            pdf_path = Path(info.get("pdf_path") or "")
            if not pdf_path.is_file():
                logging.warning("Skipping upload for BOL %s - saved PDF not found at %s.", bol, pdf_path)
                continue
            handle = open(pdf_path, "rb")
            open_files.append(handle)
            files.append(("rms_file", (pdf_path.name, handle, "application/pdf")))

        if not files:
            return {"ok": False, "message": "No PDF files found on disk to upload for this batch."}

        files.append((
            "rms_file",
            ("bol_data.json", json.dumps(bol_data_sidecar).encode("utf-8"), "application/json"),
        ))

        response = requests.post(
            f"{base_url}/api/local-rms/import",
            headers={"Authorization": f"Bearer {token}"},
            files=files,
            timeout=int(os.environ.get("EOMS_WORKER_HTTP_TIMEOUT", "120")),
        )
        response.raise_for_status()
        result = response.json()
        result["_attempted_bols"] = [normalize_bol_number(bol) for bol in batch.keys()]
        return result
    finally:
        for handle in open_files:
            try:
                handle.close()
            except Exception:
                pass


def confirmed_bols_from_upload_result(result):
    confirmed = set()
    for field in ("added_bols", "duplicate_bols", "existing_bols", "imported_bols"):
        for item in result.get(field) or []:
            if isinstance(item, dict):
                bol = item.get("normalized_bol") or item.get("bol")
            else:
                bol = item
            normalized = normalize_bol_number(bol)
            if normalized:
                confirmed.add(normalized)

    if not confirmed and result.get("ok") and not result.get("failed_bols"):
        attempted = [bol for bol in result.get("_attempted_bols") or [] if bol]
        expected_confirmed_count = int(result.get("added", 0) or 0) + int(result.get("duplicates", 0) or 0)
        if attempted and expected_confirmed_count >= len(attempted):
            confirmed.update(attempted)
    return confirmed


def bol_statuses_from_upload_result(result):
    statuses = {}
    for field, status in (("added_bols", "Imported"), ("imported_bols", "Imported"), ("duplicate_bols", "Already Exists"), ("existing_bols", "Already Exists")):
        for item in result.get(field) or []:
            bol = item.get("normalized_bol") or item.get("bol") if isinstance(item, dict) else item
            normalized = normalize_bol_number(bol)
            if normalized:
                statuses[normalized] = status

    attempted = [bol for bol in result.get("_attempted_bols") or [] if bol]
    if not statuses and result.get("ok") and attempted and not result.get("failed_bols"):
        added = int(result.get("added", 0) or 0)
        duplicates = int(result.get("duplicates", 0) or 0)
        if added >= len(attempted):
            statuses.update({bol: "Imported" for bol in attempted})
        elif duplicates >= len(attempted):
            statuses.update({bol: "Already Exists" for bol in attempted})
    return statuses


def cleanup_confirmed_local_pdfs(imported_pdfs, confirmed_bols):
    removed = []
    retained = {}
    for bol, info in (imported_pdfs or {}).items():
        normalized = normalize_bol_number(bol)
        pdf_path = Path(info.get("pdf_path") or "")
        if normalized in confirmed_bols:
            if pdf_path.is_file():
                try:
                    pdf_path.unlink()
                    removed.append(str(pdf_path))
                except Exception as exc:
                    logging.warning("Confirmed BOL %s but could not remove local PDF %s: %s", bol, pdf_path, exc)
            continue
        retry_info = dict(info)
        retry_info["failure_reason"] = retry_info.get("failure_reason") or "Not confirmed by EOMS import response."
        retained[bol] = retry_info
    return {"removed": removed, "retained": retained}


def append_sync_history(run_record):
    history = load_sync_history()
    history.append(run_record)
    save_sync_history(history)
    return run_record


def upload_local_import_to_azure(imported_pdfs, batch_size=10):
    """Push the PDFs this run just saved locally up to Azure's
    /api/local-rms/import, so the BOLs this scrape found actually show up on
    the live site - not just a status summary. RMS blocks Azure's own servers
    from scraping directly, so this upload is the only way the real data gets
    there: the scrape has to happen on a machine RMS will actually let in
    (this one), then the result gets carried over separately.

    Uploads in small batches rather than one giant request: Azure has to
    parse each PDF and geocode each address on receipt, and doing that for
    dozens of BOLs in a single request risks running long enough to hit
    Azure's platform-level timeout (separate from and shorter than gunicorn's
    own timeout), which surfaces as a 502 Bad Gateway with nothing actually
    imported. Smaller batches also mean one bad PDF only costs that batch,
    not the whole run.

    imported_pdfs: {bol_number: {"pdf_path": str, "due_date": str, "assigned_date": str}}
    as returned by app.rms_full_import_with_playwright().
    """
    run_id = str(uuid4())
    started_at = utc_now_iso()
    started_monotonic = time.monotonic()
    queue, duplicate_candidates = merge_imported_pdfs_into_queue(imported_pdfs)
    upload_entries = active_upload_entries(queue)

    if not upload_entries:
        finished_at = utc_now_iso()
        run_record = {
            "run_id": run_id,
            "start_time": started_at,
            "finish_time": finished_at,
            "duration_seconds": round(time.monotonic() - started_monotonic, 3),
            "total_scanned": len(imported_pdfs or {}),
            "imported": 0,
            "already_exists": len(duplicate_candidates),
            "failed": 0,
            "upload_errors": [],
            "operator": sync_operator(),
            "worker_version": WORKER_VERSION,
            "bols": [
                {"bol": bol, "normalized_bol": bol, "status": "Already Exists", "failure_reason": "", "upload_result": "previously confirmed", "timestamp": finished_at}
                for bol in duplicate_candidates
            ],
        }
        append_sync_history(run_record)
        logging.info("No pending local RMS PDFs to upload to Azure.")
        return {"ok": True, "message": "Nothing pending to upload.", "skipped": True, "run": run_record}

    base_url = worker_base_url()
    token, auth_mode = worker_auth_token()
    if not base_url:
        raise RuntimeError("EOMS_BASE_URL is required.")
    if not token:
        raise RuntimeError(
            "EOMS_WORKER_TOKEN is required to upload scraped BOLs to Azure "
            "(LOCAL_RMS_IMPORT_TOKEN is supported only as a legacy fallback)."
        )

    deduped = {}
    for bol, info in upload_entries.items():
        normalized = normalize_bol_number(bol)
        if not normalized:
            continue
        deduped[normalized] = {**(info or {}), "source_bol": info.get("bol") or bol}

    items = list(deduped.items())
    if not items:
        return {"ok": False, "message": "No normalized BOL numbers were available to upload.", "failed": len(imported_pdfs or {})}

    batches = [dict(items[i:i + batch_size]) for i in range(0, len(items), batch_size)]

    batch_results = []
    total_added = 0
    total_duplicates = 0
    total_need_review = 0
    all_ok = True
    confirmed_bols = set()
    failed_bols = []
    bol_statuses = {}
    for index, batch in enumerate(batches, start=1):
        logging.info(
            "Uploading batch %d/%d (%d BOL(s)) to %s/api/local-rms/import using %s authentication.",
            index,
            len(batches),
            len(batch),
            base_url,
            auth_mode,
        )
        queue = mark_queue_status(load_sync_queue(), batch.keys(), "Uploading")
        try:
            result = _upload_batch_to_azure(base_url, token, batch)
        except Exception as exc:
            logging.exception("Batch %d/%d failed to upload.", index, len(batches))
            result = {"ok": False, "message": f"Batch {index} failed: {exc}"}
            failed_bols.extend({
                "bol": bol,
                "normalized_bol": normalize_bol_number(bol),
                "reason": str(exc)[:300],
            } for bol in batch.keys())
        batch_results.append(result)
        if not result.get("ok"):
            all_ok = False
        # /api/local-rms/import (import_rms_uploaded_files()) reports counts as
        # added/duplicates/need_review - not imported/updated. Match its real
        # field names so the rolled-up totals here (and what the Automation
        # Center dashboard displays) actually reflect what happened.
        total_added += int(result.get("added", 0) or 0)
        total_duplicates += int(result.get("duplicates", 0) or 0)
        total_need_review += int(result.get("need_review", 0) or 0)
        confirmed_bols.update(confirmed_bols_from_upload_result(result))
        bol_statuses.update(bol_statuses_from_upload_result(result))
        failed_bols.extend(result.get("failed_bols") or [])

        confirmed_in_batch = confirmed_bols_from_upload_result(result)
        failed_in_batch = {normalize_bol_number(item.get("normalized_bol") or item.get("bol")) for item in result.get("failed_bols") or [] if isinstance(item, dict)}
        failed_in_batch.update({normalize_bol_number(bol) for bol in batch.keys() if not result.get("ok")})
        queue = load_sync_queue()
        queue = mark_queue_status(queue, confirmed_in_batch, "Imported")
        queue = mark_queue_status(queue, failed_in_batch - confirmed_in_batch, "Failed", result.get("message") or "Upload was not confirmed by EOMS.")

    cleanup = cleanup_confirmed_local_pdfs(deduped, confirmed_bols)
    if cleanup["retained"]:
        all_ok = False
        retained_reason = "Upload completed without per-BOL import/existing confirmation from EOMS."
        queue = load_sync_queue()
        for bol in cleanup["retained"].keys():
            if bol in queue:
                queue[bol]["status"] = "Failed"
                queue[bol]["failure_reason"] = retained_reason
                queue[bol]["updated_at"] = utc_now_iso()
        save_sync_queue(queue)

    active_after_cleanup = {}
    queue = load_sync_queue()
    for bol, entry in queue.items():
        if bol in confirmed_bols:
            continue
        active_after_cleanup[bol] = entry
    save_sync_queue(active_after_cleanup)

    finished_at = utc_now_iso()
    bol_records = []
    for bol, info in deduped.items():
        status = bol_statuses.get(bol)
        if not status and bol in confirmed_bols:
            status = "Imported"
        if not status:
            status = "Failed"
        failure = ""
        if status == "Failed":
            failure = clean((cleanup["retained"].get(bol) or {}).get("failure_reason")) or "Upload was not confirmed by EOMS."
        bol_records.append({
            "bol": clean(info.get("bol") or info.get("source_bol") or bol),
            "normalized_bol": bol,
            "status": status,
            "failure_reason": failure,
            "upload_result": next((r.get("message", "") for r in batch_results if bol in (r.get("_attempted_bols") or [])), ""),
            "timestamp": finished_at,
        })
    for bol in duplicate_candidates:
        bol_records.append({
            "bol": bol,
            "normalized_bol": bol,
            "status": "Already Exists",
            "failure_reason": "",
            "upload_result": "previously confirmed",
            "timestamp": finished_at,
        })

    run_record = {
        "run_id": run_id,
        "start_time": started_at,
        "finish_time": finished_at,
        "duration_seconds": round(time.monotonic() - started_monotonic, 3),
        "total_scanned": len(imported_pdfs or {}),
        "imported": sum(1 for item in bol_records if item["status"] == "Imported"),
        "already_exists": sum(1 for item in bol_records if item["status"] == "Already Exists"),
        "failed": sum(1 for item in bol_records if item["status"] == "Failed"),
        "upload_errors": [clean(r.get("message")) for r in batch_results if not r.get("ok") and clean(r.get("message"))],
        "operator": sync_operator(),
        "worker_version": WORKER_VERSION,
        "bols": bol_records,
    }
    append_sync_history(run_record)

    return {
        "ok": all_ok,
        "message": f"Uploaded {len(batches)} batch(es) covering {len(items)} BOL(s). "
                   f"Added {total_added}, need review {total_need_review}, "
                   f"skipped duplicates {total_duplicates}.",
        "added": total_added,
        "imported": total_added,  # kept for backward compatibility with existing dashboard/tests
        "duplicates": total_duplicates,
        "need_review": total_need_review,
        "batch_count": len(batches),
        "batch_results": batch_results,
        "confirmed_bols": sorted(confirmed_bols),
        "failed_bols": failed_bols,
        "cleanup": cleanup,
        "retained_for_retry": cleanup["retained"],
        "active_queue_count": len(load_sync_queue()),
        "run": run_record,
    }


def main():
    configure_logging()
    timestamp = datetime.now().isoformat(timespec="seconds")
    logging.info("Local visible RMS worker started.")
    edge_process = None
    report_posted = False
    raw_result = {}
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

        # RMS blocks Azure's own servers, so the scrape only ever runs here
        # (a machine RMS will actually let in). Whatever PDFs this run saved
        # locally need to be pushed to Azure separately - the status summary
        # posted below is NOT the actual BOL data, just a dashboard status.
        imported_pdfs = (raw_result or {}).get("imported_pdfs") or {}
        if imported_pdfs:
            try:
                upload_result = upload_local_import_to_azure(imported_pdfs)
                summary["upload"] = upload_result
                if not upload_result.get("ok"):
                    summary["ok"] = False
                    summary["status"] = "PARTIAL FAILURE"
                    summary["error_message"] = upload_result.get("message") or "One or more BOL uploads were not confirmed by EOMS."
                    summary.setdefault("errors", []).append(summary["error_message"])
                logging.info("Uploaded %d scraped BOL(s) to Azure via /api/local-rms/import.", len(imported_pdfs))
            except Exception as exc:
                logging.exception("Unable to upload scraped BOLs to Azure.")
                summary["ok"] = False
                summary["status"] = "PARTIAL FAILURE"
                summary["error_message"] = f"Unable to upload scraped BOLs to EOMS: {exc}"
                summary.setdefault("errors", []).append(summary["error_message"])

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
