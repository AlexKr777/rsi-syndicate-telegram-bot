@echo off
setlocal EnableExtensions

cd /d "%~dp0"
set "TARGET=%CD%\run.bat"

start "RSI Bot" /min "%ComSpec%" /c call "%TARGET%"
exit /b 0
