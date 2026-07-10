"""Diagnostic: reproduce the server-side PDF import/parse step LOCALLY,
without touching the network, to check whether the 502/hang on Azure is
caused by something in the PDF parsing logic itself (which would also show
up here) versus something specific to the Azure environment (memory,
network egress to Azure Maps, a crashing worker, etc).

This picks the exact same "first" BOL that
push_existing_local_bols_to_azure.py --limit 1 would upload, and runs
app.parse_rms_pdf() on it directly, in-process, with a hard time limit so
this script can't hang forever even if there's a real infinite loop.

Usage:
    python diagnose_local_rms_import.py
"""

import json
import os
import threading
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "diagnose-local-rms-import-script")

BASE_DIR = Path(__file__).resolve().parent
STORES_PATH = BASE_DIR / "data" / "stores.json"
SETTINGS_PATH = BASE_DIR / "data" / "settings.json"


def main():
    if not STORES_PATH.is_file():
        print(f"Could not find {STORES_PATH}")
        return 1

    stores = json.loads(STORES_PATH.read_text(encoding="utf-8"))

    target_bol = None
    target_path = None
    for store in stores:
        bol = str(store.get("bol") or "").strip()
        pdf_path = str(store.get("pdf_path") or "").strip()
        if bol and pdf_path and Path(pdf_path).is_file():
            target_bol = bol
            target_path = Path(pdf_path)
            break

    if not target_path:
        print("No BOL with a saved PDF found in data/stores.json - nothing to test.")
        return 0

    print(f"Testing BOL {target_bol}")
    print(f"PDF: {target_path}")
    print(f"File size: {target_path.stat().st_size} bytes")

    if SETTINGS_PATH.is_file():
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        key = settings.get("azure_maps_key") or ""
        print(f"Local azure_maps_key configured: {'yes' if key else 'no'} "
              f"(if 'no', geocoding is skipped locally even if Azure has a key set - "
              f"that would mean this test can't reproduce a geocode-related hang)")

    import app  # noqa: E402  (import after env setup, matches app.py's own expectations)

    result = {}
    error = {}

    def run_parse():
        try:
            result["item"] = app.parse_rms_pdf(target_path)
        except Exception as exc:
            error["exc"] = exc

    print("\nRunning app.parse_rms_pdf() in-process (30s hard limit)...")
    started = threading.Event()
    thread = threading.Thread(target=run_parse, daemon=True)
    import time
    t0 = time.monotonic()
    thread.start()
    thread.join(timeout=30)
    elapsed = time.monotonic() - t0

    if thread.is_alive():
        print(f"STILL RUNNING after {elapsed:.1f}s - parse_rms_pdf() is hanging locally too. "
              "This points to a real bug in the parsing/geocoding logic itself, not "
              "something Azure-specific.")
        return 1

    if "exc" in error:
        print(f"FAILED after {elapsed:.1f}s: {type(error['exc']).__name__}: {error['exc']}")
        return 1

    print(f"Completed in {elapsed:.2f}s. Parsed fields:")
    item = result.get("item") or {}
    for key in ("bol", "origin", "store_name", "address", "city", "state", "zip",
                "geocode_status", "status", "due_date"):
        print(f"  {key}: {item.get(key)!r}")

    if elapsed > 5:
        print("\nThis took noticeably long even locally - likely the geocoding call. "
              "On Azure, if outbound network to atlas.microsoft.com is slow/blocked, "
              "this same call could stall far longer per file.")
    else:
        print("\nFast and clean locally - the parsing logic itself is not the problem. "
              "The Azure-side failure is most likely environment-specific "
              "(worker crash/OOM, or blocked outbound network to Azure Maps).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
