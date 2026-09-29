@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   ShuttleScope Backend Setup
echo ============================================
echo.
echo Full app setup is easier from:
echo   ..\bootstrap_windows.ps1 -RunDoctor
echo.

cd /d %~dp0

python -m venv .venv
if errorlevel 1 (
    echo [ERROR] Failed to create .venv
    pause
    exit /b 1
)

echo [SETUP] Upgrading pip...
.venv\Scripts\python -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] pip upgrade failed
    pause
    exit /b 1
)

echo [SETUP] Installing backend requirements...
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)

echo.
echo Backend setup complete.
echo Start the backend with:
echo   cd backend
echo   .venv\Scripts\python main.py
echo.
pause
