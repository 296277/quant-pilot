@echo off
setlocal
title QuantPilot

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_dashboard.ps1"
set "DASHBOARD_EXIT=%ERRORLEVEL%"

if not "%DASHBOARD_EXIT%"=="0" (
    echo.
    echo Dashboard startup failed. See the message above and logs in data\processed\dashboard\.
    echo.
    pause
)

endlocal & exit /b %DASHBOARD_EXIT%
