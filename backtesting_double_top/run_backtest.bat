@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist "..\.venv\Scripts\python.exe" (
  set "PYTHON_EXE=..\.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)

echo [Double Top Backtest] Starting autonomous backtest...
echo [Double Top Backtest] Using Python: %PYTHON_EXE%
echo [Double Top Backtest] Read-only source: %~dp0..\test2\data\futures_research_cache.sqlite
echo.
%PYTHON_EXE% -m app.main --config config.yaml
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [Double Top Backtest] Finished. Results are in: %~dp0output
) else (
  echo [Double Top Backtest] Failed with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
