@echo off
setlocal enabledelayedexpansion

:: DeskGuard - Task Scheduler setup for deskguard.py (recorder) and
:: watchdog.py (fallback native-lock trigger).
::
:: WHY THIS ISN'T AN NSSM SERVICE (like the dashboard is):
:: Windows services run in Session 0, isolated from the interactive
:: desktop - they cannot open a camera tied to the logged-in user's
:: session, draw the full-screen overlay, or install the low-level
:: input hooks in input_lock.py. Both scripts need to run AS the
:: logged-in user, IN their interactive session. A "run at log on"
:: Scheduled Task does exactly that; an NSSM service cannot.
::
:: Run this file as Administrator.

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb runAs"
    exit /b
)

set "APP_DIR=%~dp0"
set "PYTHONW="
set "PYTHON="

for /f "delims=" %%i in ('where pythonw 2^>nul') do (
    if "!PYTHONW!"=="" set "PYTHONW=%%i"
)
for /f "delims=" %%i in ('where python 2^>nul') do (
    if "!PYTHON!"=="" set "PYTHON=%%i"
)
if "!PYTHONW!"=="" set "PYTHONW=!PYTHON!"
if "!PYTHON!"=="" (
    echo.
    echo ERROR: Python was not found on PATH.
    pause
    exit /b 1
)

title DeskGuard - Task Scheduler Setup

echo.
echo This will register two Scheduled Tasks that start at logon, in
echo YOUR interactive session:
echo   1. DeskGuardRecorder  -^> %APP_DIR%deskguard.py    (pythonw, silent)
echo   2. DeskGuardWatchdog  -^> %APP_DIR%watchdog.py      (pythonw, silent)
echo.
echo The watchdog must run as its own process tree so killing the
echo recorder does not also kill the thing watching it.
echo.
pause

schtasks /Create /TN "DeskGuardRecorder" /SC ONLOGON /RL HIGHEST /F ^
    /TR "\"%PYTHONW%\" \"%APP_DIR%deskguard.py\""

schtasks /Create /TN "DeskGuardWatchdog" /SC ONLOGON /RL HIGHEST /F ^
    /TR "\"%PYTHONW%\" \"%APP_DIR%watchdog.py\""

echo.
echo Done. Both tasks are set to "At log on" for this user.
echo Start them now without logging off/on again:
echo   schtasks /Run /TN "DeskGuardRecorder"
echo   schtasks /Run /TN "DeskGuardWatchdog"
echo.
echo To remove them later:
echo   schtasks /Delete /TN "DeskGuardRecorder" /F
echo   schtasks /Delete /TN "DeskGuardWatchdog" /F
echo.
pause
