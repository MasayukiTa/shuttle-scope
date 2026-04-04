@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title ShuttleScope

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "VENV=%BACKEND%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"

:: Strip trailing backslash
set "APPDIR=%ROOT:~0,-1%"

echo ============================================
echo   ShuttleScope
echo ============================================
echo.

:: Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+
    pause
    exit /b 1
)

:: Check npm
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm not found. Install Node.js
    pause
    exit /b 1
)

:: Setup Python venv (first run only)
if not exist "%PYTHON%" (
    echo [SETUP] Creating Python venv...
    python -m venv "%VENV%"
    if errorlevel 1 ( echo [ERROR] venv failed & pause & exit /b 1 )
    echo [SETUP] Installing packages...
    "%PIP%" install -r "%BACKEND%equirements.txt"
    if errorlevel 1 ( echo [ERROR] pip install failed & pause & exit /b 1 )
    echo [SETUP] Python done.
    echo.
)

:: npm install (first run only)
if not exist "%ROOT%node_modules" (
    echo [SETUP] Running npm install...
    cd /d "%ROOT%"
    npm install
    if errorlevel 1 ( echo [ERROR] npm install failed & pause & exit /b 1 )
    echo [SETUP] npm done.
    echo.
)

:: Build if output files are missing
if not exist "%ROOT%out\main\index.js" goto build
if not exist "%ROOT%outenderer\index.html" goto build
goto launch

:build
echo [BUILD] Building app (takes 1-2 min)...
cd /d "%ROOT%"
call npm run build
if errorlevel 1 ( echo [ERROR] Build failed & pause & exit /b 1 )
echo [BUILD] Done.
echo.

:launch
:: Kill old Python backend
powershell -NoProfile -Command "Stop-Process -Name python -Force -ErrorAction SilentlyContinue" >nul 2>&1
timeout /t 1 /nobreak >nul

echo [START] Launching ShuttleScope...
echo        Close this window to stop the app.
echo.
cd /d "%ROOT%"
npm run preview

