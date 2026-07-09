"""One-off helper: push the BOLs/PDFs already sitting in your local
data/stores.json up to the live Azure site, without re-running the RMS
scrape. Useful the first time you set up EOMS_BASE_URL / LOCAL_RMS_IMPORT_TOKEN
in .env after Azure Auto Grab already ran once against localhost by mistake.

Usage (from the project folder, with your .venv activated):
    python push_existing_local_bols_to_azure.py

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


def main():
    if not STORES_PATH.is_file():
        print(f"Could not find {STORES_PATH}")
        return 1

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

    print(f"Found {len(imported_pdfs)} BOL(s) with a saved PDF to upload.")
    if skipped:
        print(f"Skipping {len(skipped)} BOL(s) with a missing PDF file:")
        for bol, path in skipped[:10]:
            print(f"  - {bol}: {path}")

    if not imported_pdfs:
        print("Nothing to upload.")
        return 0

    base_url = os.environ.get("EOMS_BASE_URL") or os.environ.get("AZURE_EOMS_URL")
    print(f"Uploading to: {base_url}/api/local-rms/import")

    try:
        result = worker.upload_local_import_to_azure(imported_pdfs)
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1

    print("Result from Azure:")
    print(json.dumps(result, indent=2)[:3000])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
