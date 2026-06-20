EOMS v1.5.1 Safe Update Package

Purpose:
This package fixes the update bug where replacing the whole folder could overwrite live operational data.

This package DOES NOT include:
- data/
- bol_files/
- uploads/
- diagnostics/

Protected live files:
- data/stores.json
- data/routes.json
- data/rms_queue.json
- data/settings.json
- bol_files/Imported
- bol_files/Assigned
- bol_files/Completed
- bol_files/Need_Review
- bol_files/RMS_Backup

Update Instructions:
1. Stop EOMS with CTRL+C.
2. Extract this ZIP.
3. Copy ONLY these into your essayons-operations folder:
   - app.py
   - templates/
   - static/
   - requirements.txt if present
4. Do NOT delete or replace your data folder.
5. Do NOT delete or replace your bol_files folder.
6. Start EOMS:
   py -3.12 app.py

From now on:
Use safe update packages so imported BOLs, routes, RMS queue, settings, and saved printable BOLs stay protected.
