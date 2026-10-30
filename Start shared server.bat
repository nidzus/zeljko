@echo off
title Jyotisha - shared server
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo The environment is missing. Double-click "Install or repair.bat" first.
  echo.
  echo Press any key to close.
  pause >nul
  exit /b 1
)
".venv\Scripts\python.exe" jyotisha.py serve
echo.
echo The server has stopped. Press any key to close.
pause >nul
