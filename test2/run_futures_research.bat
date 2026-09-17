@echo off
setlocal
cd /d "%~dp0"

echo [RSI Futures Research] Starting isolated research module...

if exist "..\.venv\Scripts\python.exe" (
    set "PYTHON_BIN=..\.venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_BIN=.venv\Scripts\python.exe"
) else (
    set "PYTHON_BIN=python"
)

echo [RSI Futures Research] Using Python: %PYTHON_BIN%
echo [RSI Futures Research] Output will be saved to: %~dp0output
echo.

"%PYTHON_BIN%" run_futures_research.py %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo [RSI Futures Research] Done. Open: %~dp0output\report.html
    if exist "%~dp0output\report.html" (
        start "" "%~dp0output\report.html" >nul 2>nul
    )
) else (
    echo [RSI Futures Research] Failed with exit code %EXIT_CODE%
)

pause
exit /b %EXIT_CODE%
