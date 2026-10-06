@echo off
REM ===================================================================
REM  Ozon coffee price monitor - launcher for Windows Task Scheduler
REM  Runs ozon_monitor.py every 4 hours, appending output to logs\run.log
REM ===================================================================

setlocal

REM Always work in the folder this script lives in
cd /d "%~dp0"

REM Force UTF-8 so the rouble sign and Cyrillic survive redirection
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

REM Send the message through GitHub Actions, so the bot token stays on GitHub
REM and never has to be stored on this computer.
set "OZON_TELEGRAM_VIA_GITHUB=1"

REM Explicit interpreter; falls back to PATH lookup if it moved
set "PYTHON=D:\Python\Python312\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

if not exist "logs" mkdir "logs"

echo.>> "logs\run.log"
echo ================ %DATE% %TIME% ================>> "logs\run.log"

"%PYTHON%" ozon_monitor.py >> "logs\run.log" 2>&1

endlocal
