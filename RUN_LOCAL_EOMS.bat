@echo off
cd /d "%~dp0"
echo Starting Essayons Operations locally...
set PYTHONDONTWRITEBYTECODE=1
if not exist .venv (
  echo Creating local virtual environment...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -m venv .venv
  ) else (
    where python >nul 2>nul
    if not errorlevel 1 (
      python -m venv .venv
    ) else (
      echo Python was not found on PATH. Install Python or create .venv before running this script.
      pause
      exit /b 1
    )
  )
)
call "%CD%\.venv\Scripts\activate.bat"
"%CD%\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
"%CD%\.venv\Scripts\python.exe" -m playwright install chromium
set FLASK_APP=app.py
if not defined SECRET_KEY set SECRET_KEY=ThisIsMyTemporarySecretKey123456789
if not defined ADMIN_PASSWORD set ADMIN_PASSWORD=Admin123!
if not defined SESSION_COOKIE_SECURE set SESSION_COOKIE_SECURE=0
if not defined RMS_HEADLESS set RMS_HEADLESS=0
if not defined RMS_MANUAL_LOGIN set RMS_MANUAL_LOGIN=1
if not defined RMS_MANUAL_LOGIN_TIMEOUT_SECONDS set RMS_MANUAL_LOGIN_TIMEOUT_SECONDS=600
if not defined RMS_BROWSER set RMS_BROWSER=chrome
if not defined RMS_PROFILE_DIR set RMS_PROFILE_DIR=%CD%\data\rms_browser_profile
set DATA_DIR=%CD%\data
set UPLOAD_DIR=%CD%\uploads
set BOL_DIR=%CD%\bol_files
"%CD%\.venv\Scripts\python.exe" app.py
pause
