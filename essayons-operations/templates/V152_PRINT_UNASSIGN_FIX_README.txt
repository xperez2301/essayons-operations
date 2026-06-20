EOMS v1.5.2 Print + Unassign Fix

Fixes:
1. Printing
- Adds /bol-print/<store_id>
- Opens saved printable BOL copy
- Automatically opens browser print dialog
- User can select office printer from Windows print dialog
- Adds Print link to Route Builder stops
- Adds Print link to Dispatch Map store cards where available

2. Unassign Routes
- Adds Unassign Stop button in Route Builder
- Adds Unassign Entire Route button
- Returns stores back to Dispatch Map as Unassigned
- Moves BOL file back to Imported folder
- Removes empty routes after unassigning stops

Safe update:
This package excludes data/, bol_files/, uploads/, and diagnostics/.
Only copy app.py, templates/, static/, and requirements.txt if present.
