@echo off
setlocal
cd /d "%~dp0"

echo [RSI Futures Cache] Warming local candle cache from public archive and recent API tail...

if exist "..\.venv\Scripts\python.exe" (
    set "PYTHON_BIN=..\.venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_BIN=.venv\Scripts\python.exe"
) else (
    set "PYTHON_BIN=python"
)

echo [RSI Futures Cache] Using Python: %PYTHON_BIN%
echo [RSI Futures Cache] Cache DB: %~dp0data\futures_research_cache.sqlite
echo.

"%PYTHON_BIN%" run_futures_research.py --prefetch-only --no-open %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo [RSI Futures Cache] Warm-up finished.
) else (
    echo [RSI Futures Cache] Failed with exit code %EXIT_CODE%
)

pause
exit /b %EXIT_CODE%
