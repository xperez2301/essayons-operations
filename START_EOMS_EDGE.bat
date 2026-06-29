@echo off
cd /d "%~dp0"
echo Closing any open Edge so the profile can be automated...
taskkill /IM msedge.exe /F >nul 2>&1
timeout /t 2 >nul
echo Opening your RMS Edge profile (Profile 1) with debug port...
start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9223 --remote-allow-origins=* --profile-directory="Profile 1" https://rms.reusability.com/bills-of-lading
timeout /t 5 >nul
echo Starting EOMS (CDP mode)...
set SECRET_KEY=ThisIsMyTemporarySecretKey123456789
set ADMIN_PASSWORD=Admin123!
set SESSION_COOKIE_SECURE=0
set RMS_HEADLESS=0
set RMS_MANUAL_LOGIN=1
set RMS_BROWSER=cdp
set RMS_CDP_ENDPOINT=http://127.0.0.1:9223
set DATA_DIR=%CD%\data
set UPLOAD_DIR=%CD%\uploads
set BOL_DIR=%CD%\bol_files
"%CD%\.venv\Scripts\python.exe" app.py
pause
