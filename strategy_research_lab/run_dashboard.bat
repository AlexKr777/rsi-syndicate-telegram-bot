@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\streamlit.exe" (
  set "STREAMLIT_EXE=.venv\Scripts\streamlit.exe"
) else if exist "..\backtesting_double_top\.venv\Scripts\streamlit.exe" (
  set "STREAMLIT_EXE=..\backtesting_double_top\.venv\Scripts\streamlit.exe"
) else if exist "..\.venv\Scripts\streamlit.exe" (
  set "STREAMLIT_EXE=..\.venv\Scripts\streamlit.exe"
) else (
  set "STREAMLIT_EXE=streamlit"
)

set "DASHBOARD_PORT=8502"
set "DASHBOARD_URL=http://localhost:%DASHBOARD_PORT%"
echo [Strategy Research Lab] Starting local dashboard...
echo [Strategy Research Lab] Using Streamlit: %STREAMLIT_EXE%
echo [Strategy Research Lab] Opening browser: %DASHBOARD_URL%
echo [Strategy Research Lab] If exports are missing, run run_backtests.bat first.
echo.
set "PYTHONPATH=%CD%;%PYTHONPATH%"
start "" "%DASHBOARD_URL%"
%STREAMLIT_EXE% run app/dashboard.py --server.headless true --server.port %DASHBOARD_PORT%
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
  echo [Strategy Research Lab] Closed with exit code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%
