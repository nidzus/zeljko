@echo off
title Jyotisha - repair paths
cd /d "%~dp0"

echo Pointing the Claude config files at the app and data folders.
echo.

rem The repair uses only the Python standard library, so any Python 3 will
rem do. Prefer the project's own; fall back if .venv is broken.
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY (
  py -3 -c "pass" >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  python -c "pass" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  echo No Python could be found, so the paths cannot be repaired.
  echo Install Python 3.11, then run "Install or repair.bat" first.
  echo.
  echo Press any key to close.
  pause >nul
  exit /b 1
)

%PY% jyotisha.py repair
set "RC=%ERRORLEVEL%"

echo.
echo Press any key to close.
pause >nul
exit /b %RC%
