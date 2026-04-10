@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
set "PS1=%ROOT%bootstrap_windows.ps1"

if not exist "%PS1%" (
    echo [ERROR] bootstrap_windows.ps1 not found.
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
exit /b %errorlevel%
