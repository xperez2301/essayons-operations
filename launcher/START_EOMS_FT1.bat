@echo off
title EOMS - Field Test 1
color 1F
mode con: cols=80 lines=20

echo.
echo ==========================================================
echo           ESSAYONS OPERATIONS MANAGEMENT SYSTEM
echo                   FIELD TEST 1
echo ==========================================================
echo.

cd /d C:\Users\essay\Documents\essayons-operations

echo [1/4] Activating virtual environment...
call .venv\Scripts\activate.bat

echo [2/4] Starting EOMS server...
start "" http://127.0.0.1:5000

echo [3/4] Launching Flask...
echo.
echo EOMS is running.
echo Close this window to stop the server.
echo.

python app.py