@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
  echo Virtual environment is missing. Run run.bat once first.
  pause
  exit /b 1
)

"%VENV_PYTHON%" -m src.tools.windows_autostart sync
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Autostart sync failed with exit code %EXIT_CODE%.
  pause
  exit /b %EXIT_CODE%
)

echo.
echo Autostart sync completed.
pause
exit /b 0
