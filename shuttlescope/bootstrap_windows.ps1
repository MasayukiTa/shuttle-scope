param(
    [switch]$IncludeYolo,
    [switch]$SetupTrackNet,
    [switch]$SetupGpu,      # CUDA + onnxruntime-gpu + PyTorch をセットアップ
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

Write-Step "Checking ffmpeg"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "ffmpeg が見つかりません。winget でインストールします..." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
        if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
            Write-Host "ffmpeg: インストール完了。" -ForegroundColor Green
        } else {
            Write-Host "ffmpeg: 次回ターミナル再起動後に有効になります。" -ForegroundColor Yellow
        }
    } else {
        Write-Host "winget が見つかりません。手動で ffmpeg をインストールしてください。" -ForegroundColor Red
    }
} else {
    Write-Host "ffmpeg: OK" -ForegroundColor Green
}

Write-Step "Checking ngrok"
if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    Write-Host "ngrok が見つかりません。winget でインストールします..." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install Ngrok.Ngrok -e --accept-source-agreements --accept-package-agreements
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
        Write-Host "ngrok: インストール完了。" -ForegroundColor Green
    } else {
        Write-Host "winget が見つかりません。https://ngrok.com/download から手動でインストールしてください。" -ForegroundColor Red
    }
} else {
    Write-Host "ngrok: OK" -ForegroundColor Green
}

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

if ($SetupGpu) {
    Write-Step "Setting up GPU (CUDA + onnxruntime-gpu + PyTorch)"
    & (Join-Path $root "scripts\setup_gpu.ps1")
}

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
Write-Host "  GPU セットアップ (CUDA):  .\bootstrap_windows.ps1 -SetupGpu"
Write-Host "  YOLO 追加インストール:    .\bootstrap_windows.ps1 -IncludeYolo"
Write-Host "  TrackNet 重みDL:          .\bootstrap_windows.ps1 -SetupTrackNet"
Write-Host "  環境確認:                 .\backend\.venv\Scripts\python -m backend.tools.setup_doctor"
Write-Host "  アプリ起動:               .\start.bat"
