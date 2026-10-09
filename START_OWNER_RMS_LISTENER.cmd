@echo off
cd /d "%~dp0"
if not exist eoms_local_worker.py (
 echo Copy this update into the FULL production project first.
 pause
 exit /b 1
)
if not exist .venv\Scripts\python.exe (
 echo Create a virtual environment with: py -3 -m venv .venv
 echo Then install: .venv\Scripts\python.exe -m pip install -r requirements.txt
 pause
 exit /b 1
)
.venv\Scripts\python.exe owner_rms_listener.py
pause
