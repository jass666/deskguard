@echo off
setlocal
cd /d "%~dp0.."

for %%F in (DeskGuardRecorder.exe DeskGuardWatchdog.exe DeskGuardDashboard.exe) do (
  if not exist "dist\%%F" (
    echo Missing dist\%%F. Run scripts\DeskGuard_Build.bat first.
    pause
    exit /b 1
  )
)

if not exist "config\config.json" (
  echo Missing config\config.json.
  pause
  exit /b 1
)

rem Packaged executables resolve runtime data beside the EXE. Keep their
rem configuration aligned with the source/dashboard configuration.
if not exist "dist\config" mkdir "dist\config"
copy /y "config\config.json" "dist\config\config.json" >nul
copy /y "config\config.json" "dist\config.json" >nul

start "DeskGuard Dashboard" /d "%~dp0.." "dist\DeskGuardDashboard.exe"
start "DeskGuard Watchdog" /d "%~dp0.." "dist\DeskGuardWatchdog.exe"
start "DeskGuard Recorder" /d "%~dp0.." "dist\DeskGuardRecorder.exe"
ping 127.0.0.1 -n 4 >nul
tasklist /fi "IMAGENAME eq DeskGuardDashboard.exe" | find /i "DeskGuardDashboard.exe" >nul || (
  echo DeskGuard dashboard failed to start.
  exit /b 1
)
tasklist /fi "IMAGENAME eq DeskGuardRecorder.exe" | find /i "DeskGuardRecorder.exe" >nul || (
  echo DeskGuard recorder failed to start.
  exit /b 1
)
echo DeskGuard started. Dashboard: http://127.0.0.1:5151
