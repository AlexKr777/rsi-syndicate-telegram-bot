@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist "..\backtesting_double_top\.venv\Scripts\python.exe" (
  set "PYTHON_EXE=..\backtesting_double_top\.venv\Scripts\python.exe"
) else if exist "..\.venv\Scripts\python.exe" (
  set "PYTHON_EXE=..\.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)

echo [Strategy Research Lab] Starting multi-strategy backtests...
echo [Strategy Research Lab] Using Python: %PYTHON_EXE%
echo [Strategy Research Lab] Read-only source: %~dp0..\test2\data\futures_research_cache.sqlite
echo.
set "PYTHONPATH=%CD%;%PYTHONPATH%"
%PYTHON_EXE% -m app.main --config config.yaml
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [Strategy Research Lab] Finished. Results are in: %~dp0output
) else (
  echo [Strategy Research Lab] Failed with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
