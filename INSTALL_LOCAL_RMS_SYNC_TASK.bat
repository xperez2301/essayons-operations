@echo off
setlocal
cd /d "%~dp0"

if not exist ".env" (
  echo Missing .env. Copy .env.example to .env and set AZURE_EOMS_URL and LOCAL_RMS_IMPORT_TOKEN first.
  pause
  exit /b 1
)

schtasks /Create /TN "EOMS Local RMS Sync" /SC DAILY /ST 06:00 /F /RL LIMITED /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%~dp0tools\local_rms_upload.ps1\""
if errorlevel 1 (
  echo Failed to create scheduled task.
  pause
  exit /b 1
)

echo Scheduled task created: EOMS Local RMS Sync at 06:00 daily.
echo Keep local EOMS configured so the worker can run RMS Auto Grab with the normal browser session.
pause