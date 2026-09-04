@echo off
setlocal
cd /d "%~dp0"
title LifeContext Setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1"
if errorlevel 1 (
  echo.
  echo LifeContext setup failed. Review the message above and try again.
  pause
  exit /b 1
)
echo.
echo Setup complete. You can now run START_LIFECONTEXT.cmd.
pause
