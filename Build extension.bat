@echo off
title Jyotisha - build the Claude Desktop extension
cd /d "%~dp0"

rem Builds dist\zeljko-windows.mcpb for trying a change on this computer.
rem The published files are built by GitHub when the version number in
rem extension\manifest.json is raised and pushed.

if not exist ".venv\Scripts\python.exe" (
  echo The environment is missing. Double-click "Install or repair.bat" first.
  echo.
  echo Press any key to close.
  pause >nul
  exit /b 1
)
".venv\Scripts\python.exe" jyotisha.py extension
set "RC=%ERRORLEVEL%"
echo.
echo Press any key to close.
pause >nul
exit /b %RC%
