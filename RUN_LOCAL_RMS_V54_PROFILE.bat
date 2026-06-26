@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set SECRET_KEY=ThisIsMyTemporarySecretKey123456789
set ADMIN_PASSWORD=Admin123!
set SESSION_COOKIE_SECURE=0
set RMS_HEADLESS=0
set RMS_MANUAL_LOGIN=1
set RMS_MANUAL_LOGIN_TIMEOUT_SECONDS=600
set RMS_BROWSER=edge
set RMS_PROFILE_DIR=%~dp0RMS_Browser_Profile_Texas
if exist .venv\Scripts\activate call .venv\Scripts\activate
python app.py
pause
