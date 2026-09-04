@echo off
setlocal
cd /d "%~dp0"
title LifeContext
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1"
if errorlevel 1 (
  echo.
  echo LifeContext could not prepare its local API environment.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\launcher.py"
if errorlevel 1 pause
