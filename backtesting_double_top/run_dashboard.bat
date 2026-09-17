@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\streamlit.exe" (
  set "STREAMLIT_EXE=.venv\Scripts\streamlit.exe"
) else if exist "..\.venv\Scripts\streamlit.exe" (
  set "STREAMLIT_EXE=..\.venv\Scripts\streamlit.exe"
) else (
  set "STREAMLIT_EXE=streamlit"
)

echo [Double Top Dashboard] Starting local dashboard...
echo [Double Top Dashboard] Using Streamlit: %STREAMLIT_EXE%
echo [Double Top Dashboard] If exports are missing, run run_backtest.bat first.
echo.
set "PYTHONPATH=%CD%;%PYTHONPATH%"
set "DASHBOARD_PORT=8501"
set "DASHBOARD_URL=http://localhost:%DASHBOARD_PORT%"
echo [Double Top Dashboard] Opening browser: %DASHBOARD_URL%
start "" "%DASHBOARD_URL%"
%STREAMLIT_EXE% run app/dashboard.py --server.headless true --server.port %DASHBOARD_PORT%
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
  echo [Double Top Dashboard] Closed with exit code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%
