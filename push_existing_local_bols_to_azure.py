"""One-off helper: push the BOLs/PDFs already sitting in your local
data/stores.json up to the live Azure site, without re-running the RMS
scrape. Useful the first time you set up EOMS_BASE_URL / LOCAL_RMS_IMPORT_TOKEN
in .env after Azure Auto Grab already ran once against localhost by mistake.

Usage (from the project folder, with your .venv activated):
    python push_existing_local_bols_to_azure.py
    python push_existing_local_bols_to_azure.py --batch-size 1   # diagnostic: one BOL per request
    python push_existing_local_bols_to_azure.py --limit 1        # diagnostic: only try the first BOL at all

Requires .env to have EOMS_BASE_URL pointing at the live Azure site and
LOCAL_RMS_IMPORT_TOKEN matching what's set in Azure App Service settings.
"""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "push-existing-local-bols-script")

import eoms_local_worker as worker

BASE_DIR = Path(__file__).resolve().parent
STORES_PATH = BASE_DIR / "data" / "stores.json"


def parse_args(argv):
    batch_size = 10
    limit = None
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--batch-size":
            batch_size = int(args.pop(0))
        elif arg == "--limit":
            limit = int(args.pop(0))
    return batch_size, limit


def main():
    if not STORES_PATH.is_file():
        print(f"Could not find {STORES_PATH}")
        return 1

    batch_size, limit = parse_args(sys.argv[1:])

    stores = json.loads(STORES_PATH.read_text(encoding="utf-8"))

    imported_pdfs = {}
    skipped = []
    for store in stores:
        bol = str(store.get("bol") or "").strip()
        pdf_path = str(store.get("pdf_path") or "").strip()
        if not bol or not pdf_path:
            continue
        if not Path(pdf_path).is_file():
            skipped.append((bol, pdf_path))
            continue
        imported_pdfs[bol] = {
            "pdf_path": pdf_path,
            "due_date": store.get("due_date", ""),
            "assigned_date": store.get("assigned_date", ""),
        }
        if limit and len(imported_pdfs) >= limit:
            break

    print(f"Found {len(imported_pdfs)} BOL(s) with a saved PDF to upload (batch size {batch_size}).")
    if skipped:
        print(f"Skipping {len(skipped)} BOL(s) with a missing PDF file:")
        for bol, path in skipped[:10]:
            print(f"  - {bol}: {path}")

    if not imported_pdfs:
        print("Nothing to upload.")
        return 0

    base_url = os.environ.get("EOMS_BASE_URL") or os.environ.get("AZURE_EOMS_URL")
    print(f"Uploading to: {base_url}/api/local-rms/import")

    import time
    started = time.monotonic()
    try:
        result = worker.upload_local_import_to_azure(imported_pdfs, batch_size=batch_size)
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc} (after {time.monotonic() - started:.1f}s)")
        return 1
    elapsed = time.monotonic() - started

    print(f"Result from Azure (took {elapsed:.1f}s):")
    print(json.dumps(result, indent=2)[:3000])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
