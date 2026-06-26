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
echo Starting user-controlled Edge for RMS...
echo Log into RMS in this window, then run Auto Grab in EOMS.
start "" "%EDGE_EXE%" --remote-debugging-port=9222 --user-data-dir="%RMS_DEBUG_PROFILE%" https://rms.reusability.com/bills-of-lading
