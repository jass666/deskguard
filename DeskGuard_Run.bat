@echo off
setlocal
cd /d "%~dp0"

if not exist "dist\DeskGuardRecorder.exe" (
  echo Build first by running DeskGuard_Build.bat.
  pause
  exit /b 1
)

start "DeskGuard Dashboard" /d "%~dp0" "dist\DeskGuardDashboard.exe"
start "DeskGuard Watchdog" /d "%~dp0" "dist\DeskGuardWatchdog.exe"
start "DeskGuard Recorder" /d "%~dp0" "dist\DeskGuardRecorder.exe"
echo DeskGuard started. Dashboard: http://127.0.0.1:5151
