@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title ShuttleScope

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "VENV=%BACKEND%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"

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
    "%PIP%" install -r "%BACKEND%\requirements.txt"
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

:: Kill old Python backend
powershell -NoProfile -Command "Stop-Process -Name python -Force -ErrorAction SilentlyContinue" >nul 2>&1
timeout /t 1 /nobreak >nul

:: Launch
:: - 初回: main+preload ビルド(0.5s) → Electron起動(スプラッシュ) → renderer並行ビルド(10s)
:: - 2回目以降: main+preload ビルド(0.5s) → Electron起動 → すぐアプリ表示
cd /d "%ROOT%"
npm run start
