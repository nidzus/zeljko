@echo off
title Jyotisha - test friend
cd /d "%~dp0"
echo Opens Claude Code the way a friend would see the advisor: only the
echo shared server, no plugin, none of the family data.
echo "Start shared server.bat" must already be running in another window.
echo.
choice /c AB /m "Which test friend, A or B"
if errorlevel 2 (set "WHO=b") else (set "WHO=a")
set "WORK=%TEMP%\jyotisha-friend-%WHO%"
if not exist "%WORK%" mkdir "%WORK%"
set "CONFIG=%~dp0tools\friend-%WHO%.mcp.json"
cd /d "%WORK%"
echo.
echo In Claude Code type  /mcp  , choose jyotisha-%WHO% and Authenticate.
echo.
claude --strict-mcp-config --mcp-config "%CONFIG%"
