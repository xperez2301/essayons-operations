EOMS v1.1 RMS Login Automation

What works in this build:
- Save RMS username/password locally in Settings
- Test RMS Login opens Chromium browser
- Logs into RMS
- Navigates to Bills of Lading page
- Scans BOL hyperlinks
- Saves diagnostic screenshot to diagnostics/
- Writes sync history

Before running:
    pip install -r requirements.txt
    python -m playwright install chromium

Test:
    python app.py
    open http://127.0.0.1:5000/settings
    save RMS credentials
    open http://127.0.0.1:5000/rms-sync
    click Test RMS Login
    click Scan RMS BOL List

Next build:
- Open each BOL
- Open Printable Bill of Lading
- Extract corner posts
- Import into Dispatch Map automatically
