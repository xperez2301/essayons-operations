@echo off
setlocal
cd /d "%~dp0"

if not exist ".env" (
  echo Missing .env. Copy .env.example to .env and set EOMS_BASE_URL and EOMS_WORKER_TOKEN first.
  pause
  exit /b 1
)

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "WORKER_SCRIPT=%~dp0eoms_local_worker.py"

if not exist "%PYTHON_EXE%" (
  echo Missing %PYTHON_EXE%. Create the local .venv before installing the task.
  pause
  exit /b 1
)

schtasks /Create /TN "EOMS Local RMS Sync" /SC DAILY /ST 06:00 /F /RL LIMITED /TR "\"%PYTHON_EXE%\" \"%WORKER_SCRIPT%\""
if errorlevel 1 (
  echo Failed to create scheduled task.
  pause
  exit /b 1
)

echo Scheduled task created: EOMS Local RMS Sync at 06:00 daily.
echo Keep visible Edge running with remote debugging enabled on port 9223.
pause
