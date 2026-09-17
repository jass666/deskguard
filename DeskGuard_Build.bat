@echo off
setlocal
cd /d "%~dp0"

echo Installing DeskGuard dependencies...
py -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo Building standalone DeskGuard executables...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist DeskGuard_*.spec del /q DeskGuard_*.spec

py -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name DeskGuardRecorder deskguard.py
if errorlevel 1 exit /b 1
py -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name DeskGuardWatchdog watchdog.py
if errorlevel 1 exit /b 1
py -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --collect-all imageio_ffmpeg ^
  --name DeskGuardDashboard dashboard.py
if errorlevel 1 exit /b 1

echo.
echo Build complete. Files are in:
echo   %CD%\dist\DeskGuardRecorder.exe
echo   %CD%\dist\DeskGuardWatchdog.exe
echo   %CD%\dist\DeskGuardDashboard.exe
echo.
echo Run DeskGuard_Run.bat from this folder to start all three.
pause
