@echo off
echo Installing EOMS...

if not exist .venv (
    python -m venv .venv
)

call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo EOMS install complete.
pause
