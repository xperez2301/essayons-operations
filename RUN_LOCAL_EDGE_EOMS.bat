@echo off
cd /d "%~dp0"
set SECRET_KEY=ThisIsMyTemporarySecretKey123456789
set ADMIN_PASSWORD=Admin123!
set RMS_HEADLESS=0
set RMS_MANUAL_LOGIN=1
set RMS_BROWSER=edge
set RMS_START_URL=https://rms.reusability.com
python app.py
pause
