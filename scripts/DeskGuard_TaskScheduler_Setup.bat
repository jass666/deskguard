@echo off
setlocal

:: Keep the user-facing entry point as a .bat, but do the actual task
:: registration in PowerShell.  schtasks.exe is very easy to misquote when
:: both the interpreter and the .py path contain spaces.
set "SETUP_PS1=%~dp0DeskGuard_TaskScheduler_Setup.ps1"
if not exist "%SETUP_PS1%" (
    echo ERROR: Missing "%SETUP_PS1%".
    pause
    exit /b 1
)

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process PowerShell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%SETUP_PS1%'"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SETUP_PS1%"
set "RESULT=%errorLevel%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
