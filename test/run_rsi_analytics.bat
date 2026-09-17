@echo off
setlocal

cd /d "%~dp0"
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "DB_PATH=%PROJECT_ROOT%\data\rsi_alerts.db"
set "OUTPUT_DIR=%SCRIPT_DIR%output"
set "REPORT_HTML=%OUTPUT_DIR%\report.html"
set "PYTHON_EXE="
set "RSI_ANALYTICS_SEND_TELEGRAM=1"

echo [INFO] RSI analytics launcher
echo [INFO] Script dir: %SCRIPT_DIR%
echo [INFO] Project root: %PROJECT_ROOT%

if not exist "%DB_PATH%" (
    echo [ERROR] SQLite database not found: %DB_PATH%
    echo [ERROR] The analytics tool only reads existing history and cannot run without the DB.
    echo.
    pause
    exit /b 1
)

if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
) else if exist "%SCRIPT_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo [INFO] Using Python: %PYTHON_EXE%
echo [INFO] Database: %DB_PATH%
echo [INFO] Telegram delivery: enabled for premium bot
echo.

"%PYTHON_EXE%" "%SCRIPT_DIR%run_rsi_analytics.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo [INFO] Analytics completed.
    echo [INFO] Output folder: %OUTPUT_DIR%
    if exist "%REPORT_HTML%" (
        echo [INFO] Opening HTML report...
        start "" "%REPORT_HTML%"
    ) else (
        echo [WARN] HTML report was not found: %REPORT_HTML%
    )
) else (
    echo [ERROR] Analytics failed with exit code %EXIT_CODE%.
    echo [ERROR] See traceback above.
)

echo.
pause
endlocal & exit /b %EXIT_CODE%
