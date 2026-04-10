param(
    [switch]$IncludeYolo,
    [switch]$SetupTrackNet,
    [switch]$RunDoctor
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$venv = Join-Path $backend ".venv"
$python = Join-Path $venv "Scripts\python.exe"
$pip = Join-Path $venv "Scripts\pip.exe"

function Write-Step($message) {
    Write-Host ""
    Write-Host "== $message ==" -ForegroundColor Cyan
}

function Assert-Command($name, $installHint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name が見つかりません。$installHint"
    }
}

Write-Host "ShuttleScope Windows Bootstrap" -ForegroundColor Green
Write-Host "Root: $root"

Write-Step "Checking prerequisites"
Assert-Command "python" "Python 3.10+ をインストールしてください。"
Assert-Command "npm" "Node.js 18+ をインストールしてください。"

if (-not (Test-Path $python)) {
    Write-Step "Creating Python venv"
    Push-Location $backend
    python -m venv .venv
    Pop-Location
}

Write-Step "Installing backend requirements"
& $python -m pip install --upgrade pip
& $pip install -r (Join-Path $backend "requirements.txt")

if ($IncludeYolo) {
    Write-Step "Installing YOLO runtime"
    & $pip install ultralytics
}

Write-Step "Installing frontend dependencies"
Push-Location $root
npm install
Pop-Location

if ($SetupTrackNet) {
    Write-Step "Setting up TrackNet weights and exports"
    Push-Location $root
    & $python -m backend.tracknet.setup all
    Pop-Location
}

if ($RunDoctor) {
    Write-Step "Running environment doctor"
    Push-Location $root
    & $python -m backend.tools.setup_doctor
    Pop-Location
}

Write-Step "Done"
Write-Host "Next steps:" -ForegroundColor Green
Write-Host "  1. Optional YOLO install: .\bootstrap_windows.ps1 -IncludeYolo"
Write-Host "  2. Optional TrackNet setup: .\bootstrap_windows.ps1 -SetupTrackNet"
Write-Host "  3. Check environment:    .\backend\.venv\Scripts\python -m backend.tools.setup_doctor"
Write-Host "  4. Start app:            .\start.bat"
