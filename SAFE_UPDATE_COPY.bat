@echo off
echo EOMS Safe Update Copy - Admin Login Lockdown
set /p TARGET=Enter full path to essayons-operations folder: 
if not exist "%TARGET%" (
    echo Target folder does not exist.
    pause
    exit /b 1
)
copy /Y app.py "%TARGET%\app.py"
if exist templates robocopy templates "%TARGET%\templates" /E
if exist static robocopy static "%TARGET%\static" /E
if exist requirements.txt copy /Y requirements.txt "%TARGET%\requirements.txt"
echo Safe update complete.
pause
