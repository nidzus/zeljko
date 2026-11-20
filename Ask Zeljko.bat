@echo off
title Zeljko
cd /d "%~dp0"
echo Starting Claude Code with the zeljko plugin.
echo.
echo   /zeljko:onboard   set up a profile
echo   /zeljko:ask       ask about a decision
echo   /zeljko:journal   review past advice
echo.
claude --plugin-dir ./zeljko-plugin
