@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
set "SETUP_MARKER=%CD%\.venv\.setup_complete"

if not exist "%VENV_PYTHON%" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 goto :setup_failed
)

if not exist ".env" (
  if exist ".env.example" (
    echo Creating .env from .env.example...
    copy /Y ".env.example" ".env" >nul
  ) else (
    echo Missing .env and .env.example.
    goto :setup_failed
  )
)

echo Syncing Windows autostart setting...
"%VENV_PYTHON%" -m src.tools.windows_autostart sync
if errorlevel 1 (
  echo Warning: failed to sync Windows autostart. The bot will still continue to start.
)

if not exist "%SETUP_MARKER%" (
  echo Installing dependencies...
  "%VENV_PYTHON%" -m pip install --upgrade pip
  if errorlevel 1 goto :setup_failed

  "%VENV_PYTHON%" -m pip install -r requirements.txt
  if errorlevel 1 goto :setup_failed

  type nul > "%SETUP_MARKER%"
)

echo Starting RSI bot...
echo Crypto Pay webhook URL will be written to runtime\webhook_url.txt when ngrok becomes ready.
"%VENV_PYTHON%" -m src.main
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Bot stopped with exit code %EXIT_CODE%.
  echo Check logs\rsi_bot.log and your .env settings.
  pause
  exit /b %EXIT_CODE%
)

exit /b 0

:setup_failed
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" set "EXIT_CODE=1"
echo.
echo Setup failed with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
