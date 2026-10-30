@echo off
title Jyotisha
cd /d "%~dp0"
echo Starting Claude Code with the jyotisha plugin.
echo.
echo   /jyotisha:onboard   set up a profile
echo   /jyotisha:ask       ask about a decision
echo   /jyotisha:journal   review past advice
echo.
claude --plugin-dir ./jyotisha-plugin
