@echo off
title EOMS - Field Test 1

echo.
echo ============================================
echo      ESSAYONS OPERATIONS MANAGEMENT SYSTEM
echo               FIELD TEST 1
echo ============================================
echo.

cd /d C:\Users\essay\Documents\essayons-operations

echo Activating Python Environment...
call .venv\Scripts\activate.bat

echo.
echo Starting EOMS...
echo.

start "" http://127.0.0.1:5000

python app.py

echo.
echo EOMS has stopped.
pause