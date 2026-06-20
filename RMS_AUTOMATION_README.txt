EOMS v1.2 Full RMS Multi-Page Import Engine

What this build does:
- Logs into RMS using saved Settings
- Opens Bills of Lading page
- Attempts to increase rows per page
- Scans pagination across all pages
- Collects BOL links, not just first 20
- Opens each BOL detail page
- Opens Printable Bill of Lading
- Extracts:
  BOL number
  Origin/store number
  Store name
  Address/city/state/zip
  Corner Post quantity
  DRB quantities
  Wood Shelf quantity
  Total BOL weight
- Calculates racks using Corner Posts / 4
- Imports new BOL records to Dispatch Map
- Saves printable BOL HTML into bol_files/Imported or bol_files/Need_Review by year/month
- Skips duplicates
- Writes sync history

Run:
    py -3.12 -m pip install -r requirements.txt
    py -3.12 -m playwright install chromium
    py -3.12 app.py

Test:
    /settings -> save RMS credentials
    /rms-sync -> click Sync All RMS BOL Pages
