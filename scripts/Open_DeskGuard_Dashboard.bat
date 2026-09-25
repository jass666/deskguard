@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Open_DeskGuard_Dashboard.ps1"
if errorlevel 1 pause
