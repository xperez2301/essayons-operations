EOMS v1.3.5 Direct Print Import Fix

Fixes:
- Import Selected now goes directly to:
  https://rms.reusability.com/bills-of-lading/{BOL}/print
- Parser improved for RMS printable table layout
- Adds Repair/Parse button in RMS Queue
- Repair/Parse re-reads existing bad BOLs and updates stores.json
- Correctly sends valid records to Dispatch Map with status Unassigned

Test:
1. Run py -3.12 app.py
2. Open /rms-queue
3. Click Repair/Parse on BOL 945537
4. Open /dispatch-map
5. If parser succeeds, BOL appears on map.
