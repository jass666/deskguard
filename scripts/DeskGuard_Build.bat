@echo off
setlocal
cd /d "%~dp0.."

echo Stopping existing packaged processes so PyInstaller can replace them...
schtasks /end /tn "\DeskGuardWatchdog" >nul 2>&1
schtasks /end /tn "\DeskGuardRecorder" >nul 2>&1
taskkill /f /im DeskGuardRecorder.exe >nul 2>&1
taskkill /f /im DeskGuardWatchdog.exe >nul 2>&1
taskkill /f /im DeskGuardDashboard.exe >nul 2>&1
ping 127.0.0.1 -n 3 >nul

for %%F in (DeskGuardRecorder.exe DeskGuardWatchdog.exe DeskGuardDashboard.exe) do (
  if exist "dist\%%F" (
    ren "dist\%%F" "%%F.build-lock-test" >nul 2>&1
    if errorlevel 1 (
      echo ERROR: dist\%%F is still locked.
      echo Restart Windows, then run this build again.
      exit /b 1
    )
    ren "dist\%%F.build-lock-test" "%%F" >nul 2>&1
  )
)

echo Installing DeskGuard dependencies...
py -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo Building standalone DeskGuard executables...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist DeskGuard_*.spec del /q DeskGuard_*.spec

py -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name DeskGuardRecorder src\deskguard.py
if errorlevel 1 exit /b 1
py -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name DeskGuardWatchdog src\watchdog.py
if errorlevel 1 exit /b 1
py -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --collect-all imageio_ffmpeg ^
  --name DeskGuardDashboard src\dashboard.py
if errorlevel 1 exit /b 1

if not exist dist\DeskGuardRecorder.exe exit /b 1
if not exist dist\DeskGuardWatchdog.exe exit /b 1
if not exist dist\DeskGuardDashboard.exe exit /b 1
if not exist dist\config mkdir dist\config
copy /y config\config.json dist\config\config.json >nul
copy /y config\config.json dist\config.json >nul

echo.
echo Build complete. Files are in:
echo   %CD%\dist\DeskGuardRecorder.exe
echo   %CD%\dist\DeskGuardWatchdog.exe
echo   %CD%\dist\DeskGuardDashboard.exe
echo.
echo Run DeskGuard_Run.bat from this folder to start all three.
pause
