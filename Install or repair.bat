@echo off
title Jyotisha - install or repair
cd /d "%~dp0"

rem Builds .venv if it is missing or broken, links the data folder, points
rem the Claude config files here, turns on the privacy check and runs every
rem suite. Run with /force to rebuild .venv even when it looks healthy.
set "FORCE="
if /i "%~1"=="/force" set "FORCE=--force"

rem Any Python 3 can start jyotisha.py; it then finds Python 3.11 itself.
rem Never the one inside .venv, which may be the thing being rebuilt.
set "PY="
py -3.11 -c "pass" >nul 2>nul
if not errorlevel 1 set "PY=py -3.11"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY (
  py -3 -c "pass" >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  python -c "pass" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto :nopython

echo ============================================================
echo  Jyotisha advisor - install or repair
echo ============================================================
echo.
%PY% jyotisha.py install %FORCE%
if errorlevel 1 goto :fail
echo.
echo Press any key to close.
pause >nul
exit /b 0

:nopython
echo ------------------------------------------------------------
echo  Python 3.11 is not installed, so the environment cannot be
echo  built. Install it from:
echo.
echo    https://www.python.org/downloads/release/python-3119/
echo.
echo  Choose the 64-bit Windows installer. Python 3.12 or newer
echo  will NOT work for this project. Then run this file again.
echo ------------------------------------------------------------

:fail
echo.
echo ------------------------------------------------------------
echo  Did not finish. The reason is above.
echo ------------------------------------------------------------
echo.
echo Press any key to close.
pause >nul
exit /b 1
