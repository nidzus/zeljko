@echo off
title Jyotisha - backup
cd /d "%~dp0"

rem Where the copies go is "backup_folder" in settings.json in your data
rem folder (default: jyotisha-backups in your user folder). For a USB or
rem second drive, put something like  E:\Jyotisha-Backups  there.
rem Run with /quiet (Task Scheduler does) to skip the "press any key" wait.

if not exist ".venv\Scripts\python.exe" (
  echo The environment is missing. Double-click "Install or repair.bat" first.
  echo.
  echo Press any key to close.
  pause >nul
  exit /b 1
)
".venv\Scripts\python.exe" jyotisha.py backup
set "RC=%ERRORLEVEL%"
if /i "%~1"=="/quiet" exit /b %RC%
echo.
echo Press any key to close.
pause >nul
exit /b %RC%
