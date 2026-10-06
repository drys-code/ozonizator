@echo off
REM ===================================================================
REM  Ozon coffee price monitor - launcher
REM  Runs ozon_monitor.py and appends output to logs\run.log
REM  Intended to be started every 4 hours by Windows Task Scheduler.
REM ===================================================================

setlocal
cd /d "%~dp0"

set "PYTHON=py"
where py >nul 2>&1 || set "PYTHON=python"

if not exist "logs" mkdir "logs"

echo. >> "logs\run.log"
echo ================ %DATE% %TIME% ================ >> "logs\run.log"

"%PYTHON%" ozon_monitor.py >> "logs\run.log" 2>&1

endlocal
