@echo off
cd /d "%~dp0"
set EDGE_EXE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe
if not exist "%EDGE_EXE%" set EDGE_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe
if not exist "%EDGE_EXE%" (
  echo Microsoft Edge was not found.
  pause
  exit /b 1
)
echo This starts Edge on CDP port 9223 using your normal Edge profile.
echo Close all regular Edge windows before continuing, or Edge may ignore the debugger flag.
echo.
pause
start "" "%EDGE_EXE%" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9223 --remote-allow-origins=* --no-first-run --no-default-browser-check https://rms.reusability.com/bills-of-lading