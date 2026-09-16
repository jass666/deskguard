@echo off
setlocal enabledelayedexpansion

:: DeskGuard NSSM dashboard service setup and control
:: Run this file as Administrator.

:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb runAs"
    exit /b
)

set "SERVICE=DeskGuardDashboard"
set "APP_DIR=%~dp0"
set "PYTHON="
set "NSSM="
set "LOG_DIR=%APP_DIR%logs"

title DeskGuard - NSSM Setup and Control

:: ----------------------------------------------------------------
:: AUTO-DETECT PYTHON
:: ----------------------------------------------------------------
for /f "delims=" %%i in ('where python 2^>nul') do (
    if "!PYTHON!"=="" set "PYTHON=%%i"
)
if "!PYTHON!"=="" (
    echo.
    echo ERROR: Python was not found on PATH.
    echo Install Python or update this script with its full path.
    echo.
    pause
    exit /b 1
)

:: ----------------------------------------------------------------
:: FIND NSSM
:: ----------------------------------------------------------------
if exist "C:\nssm\nssm.exe" set "NSSM=C:\nssm\nssm.exe"
if "!NSSM!"=="" if exist "%APP_DIR%nssm.exe" set "NSSM=%APP_DIR%nssm.exe"
if "!NSSM!"=="" (
    for /f "delims=" %%i in ('where nssm 2^>nul') do (
        if "!NSSM!"=="" set "NSSM=%%i"
    )
)
if "!NSSM!"=="" (
    echo.
    echo ERROR: NSSM was not found.
    echo Place nssm.exe at C:\nssm\nssm.exe or add it to PATH.
    echo.
    pause
    exit /b 1
)

if not exist "%APP_DIR%dashboard.py" (
    echo.
    echo ERROR: dashboard.py was not found in:
    echo %APP_DIR%
    echo.
    pause
    exit /b 1
)

:MENU
cls
echo.
echo ==========================================
echo   DESKGUARD NSSM DASHBOARD CONTROL
echo ==========================================
echo.
echo Python   : %PYTHON%
echo App Dir  : %APP_DIR%
echo Service  : %SERVICE%
echo Address  : http://127.0.0.1:5151
echo.
echo --- SERVICE CONTROL ---
echo [1] Start dashboard
echo [2] Stop dashboard
echo [3] Restart dashboard
echo [4] Check status and logs
echo.
echo --- SETUP ---
echo [5] Install service
echo [6] Reinstall service
echo [7] Uninstall service
echo.
echo [0] Exit
echo.

choice /c 12345670 /n /m "Select option: "
if errorlevel 8 goto EXIT
if errorlevel 7 goto UNINSTALL
if errorlevel 6 goto REINSTALL
if errorlevel 5 goto INSTALL
if errorlevel 4 goto STATUS
if errorlevel 3 goto RESTART
if errorlevel 2 goto STOP
if errorlevel 1 goto START

:START
echo.
echo Starting %SERVICE%...
%NSSM% start %SERVICE%
if %errorlevel% equ 0 (echo Started successfully.) else (echo Failed to start.)
pause
goto MENU

:STOP
echo.
echo Stopping %SERVICE%...
%NSSM% stop %SERVICE%
if %errorlevel% equ 0 (echo Stopped successfully.) else (echo Failed to stop; it may already be stopped.)
pause
goto MENU

:RESTART
echo.
echo Restarting %SERVICE%...
%NSSM% restart %SERVICE%
if %errorlevel% equ 0 (echo Restarted successfully.) else (echo Failed to restart.)
pause
goto MENU

:STATUS
echo.
%NSSM% status %SERVICE%
echo.
echo --- Last 15 lines of dashboard error output ---
if exist "%LOG_DIR%dashboard-service-error.log" (
    powershell -Command "Get-Content -LiteralPath '%LOG_DIR%dashboard-service-error.log' -Tail 15"
) else (
    echo (no error log yet)
)
echo.
pause
goto MENU

:INSTALL
echo.
echo Installing %SERVICE%...
%NSSM% status %SERVICE% >nul 2>&1
if %errorlevel% equ 0 (
    echo Service already exists. Use option 6 to reinstall.
    pause
    goto MENU
)
call :DO_INSTALL
echo Dashboard installed and started at http://127.0.0.1:5151
pause
goto MENU

:REINSTALL
echo.
echo Reinstalling %SERVICE%...
%NSSM% stop %SERVICE% >nul 2>&1
timeout /t 2 >nul
%NSSM% remove %SERVICE% confirm >nul 2>&1
timeout /t 2 >nul
call :DO_INSTALL
echo Dashboard reinstalled and started at http://127.0.0.1:5151
pause
goto MENU

:UNINSTALL
echo.
echo This removes the Windows service only; recordings and logs will remain.
choice /c YN /m "Continue?"
if errorlevel 2 goto MENU
%NSSM% stop %SERVICE% >nul 2>&1
timeout /t 2 >nul
%NSSM% remove %SERVICE% confirm
pause
goto MENU

:DO_INSTALL
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
%NSSM% install %SERVICE% "%PYTHON%" "%APP_DIR%dashboard.py"
%NSSM% set %SERVICE% AppDirectory "%APP_DIR%"
%NSSM% set %SERVICE% Start SERVICE_AUTO_START
%NSSM% set %SERVICE% AppRestartDelay 3000
%NSSM% set %SERVICE% AppStdout "%LOG_DIR%dashboard-service.log"
%NSSM% set %SERVICE% AppStderr "%LOG_DIR%dashboard-service-error.log"
%NSSM% start %SERVICE%
goto :eof

:EXIT
exit /b 0
