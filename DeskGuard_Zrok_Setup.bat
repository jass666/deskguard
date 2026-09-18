@echo off
setlocal
cd /d "%~dp0"

title DeskGuard - zrok Setup

set "ZROK=%~dp0.zrok\zrok2.exe"
set "START_SCRIPT=%~dp0Start_DeskGuard_Public.ps1"

if not exist "%ZROK%" (
  echo.
  echo zrok2.exe was not found at:
  echo   %ZROK%
  echo.
  echo Download the official zrok2 Windows release and place zrok2.exe there.
  echo.
  pause
  exit /b 1
)

if not exist "%START_SCRIPT%" (
  echo ERROR: Start_DeskGuard_Public.ps1 was not found.
  pause
  exit /b 1
)

echo.
echo DeskGuard zrok setup
echo ====================
echo.
echo Your zrok enable token is used only by zrok and is not written here.
set /p "ENABLE_TOKEN=Paste your zrok enable token: "
if "%ENABLE_TOKEN%"=="" (
  echo No token supplied.
  exit /b 1
)

echo.
echo Enabling zrok environment...
"%ZROK%" enable "%ENABLE_TOKEN%" --headless
if errorlevel 1 exit /b 1

echo.
echo Reserving the stable public name deskguard...
"%ZROK%" create name deskguard

echo.
echo Registering the startup task...
schtasks /Create /TN "DeskGuard Public Share" /SC ONLOGON /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ^"%START_SCRIPT%^"" /F
if errorlevel 1 (
  echo Could not register the startup task.
  pause
  exit /b 1
)

echo.
echo Starting DeskGuard dashboard and zrok share now...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%START_SCRIPT%"

echo.
echo Setup complete.
echo URL: https://deskguard.shares.zrok.io
echo Use the DeskGuard dashboard password at that URL.
echo.
pause
