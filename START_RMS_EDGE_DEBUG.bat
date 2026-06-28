@echo off
cd /d "%~dp0"
set RMS_DEBUG_PROFILE=%CD%\runtime\rms_user_edge_debug_profile
if not exist "%RMS_DEBUG_PROFILE%" mkdir "%RMS_DEBUG_PROFILE%"
set EDGE_EXE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe
if not exist "%EDGE_EXE%" set EDGE_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe
if not exist "%EDGE_EXE%" (
  echo Microsoft Edge was not found.
  pause
  exit /b 1
)
echo Starting user-controlled Edge for RMS on CDP port 9222...
echo Log into RMS in this window, then run Auto Grab in EOMS.
start "" "%EDGE_EXE%" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%RMS_DEBUG_PROFILE%" --no-first-run --no-default-browser-check --disable-features=msEdgeStartupBoost https://rms.reusability.com/bills-of-lading