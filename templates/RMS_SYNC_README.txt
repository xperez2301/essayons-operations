EOMS v1.0 RMS Sync Foundation

This package adds:
- RMS Sync page
- RMS Settings page with login URL and BOL URL
- Sync history storage in data/sync_history.json
- Test Connection Foundation button
- Sync Open BOLs Foundation button
- Playwright dependency ready for the next automation build

Next step:
Run once in VS Code terminal after install:
    pip install -r requirements.txt
    python -m playwright install chromium

Then EOMS v1.1 can add full browser automation:
Login RMS > Bills of Lading > Open BOL > Printable BOL > Extract Corner Posts > Import.
