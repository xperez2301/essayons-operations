EOMS v1.4.0 Dispatch Control Center

Built from v1.3.9 stable and patched:
- Fixed app.py indentation/syntax errors
- Import/Re-import Selected uses direct printable RMS parser
- Repair/Parse no longer needed for normal imports
- Pin click auto-selects matching Available Store card
- Available Stores panel is smaller/scrollable
- Numbered custom pins
- Pin colors by due date:
  Green = more than 4 days remaining or no due date captured
  Amber = due within 4 days
  Red = past due
- Due date fields retained in stores and RMS queue
- Dispatch map debug endpoint retained

Run:
    py -3.12 app.py

Test:
1. /rms-queue
2. Import/Re-import one selected BOL
3. /dispatch-map
4. Click a pin and confirm it selects/highlights the store card
