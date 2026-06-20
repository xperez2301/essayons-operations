@echo off
echo EOMS Safe Update Copy
echo Copies program files only. It will NOT touch data or BOL files.
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
echo Safe update complete. Data was not touched.
pause
