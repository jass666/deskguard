@echo off
setlocal
set "ACT=%~1"
if "%ACT%"=="" set "ACT=kill"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0DeskGuard_KillSwitch.ps1" -Action %ACT%
