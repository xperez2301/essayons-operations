@echo off
cd /d "%~dp0"
echo Starting Essayons Operations locally...
if not exist .venv (
  py -m venv .venv
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
set FLASK_APP=app.py
set DATA_DIR=%CD%\data
set UPLOAD_DIR=%CD%\uploads
set BOL_DIR=%CD%\bol_files
python app.py
pause
