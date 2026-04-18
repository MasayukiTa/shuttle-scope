# ShuttleScope GPU セットアップスクリプト (Windows PowerShell)
# CUDA 12.8 + onnxruntime-gpu + PyTorch (Blackwell 対応) + ngrok を一括セットアップする。
#
# 前提:
#   - .\backend\.venv\ が存在すること（start.bat または bootstrap_windows.ps1 で作成済み）
#   - NVIDIA ドライバ 560 以降 / CUDA 12.8 互換 GPU（RTX 40/50 シリーズ等）
#
# 使い方:
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_gpu.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPy  = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
$pip     = Join-Path $repoRoot "backend\.venv\Scripts\pip.exe"

if (-not (Test-Path $venvPy)) {
    Write-Error "venv が見つかりません: $venvPy  — 先に start.bat または bootstrap_windows.ps1 を実行してください"
    exit 1
}

function Write-Step($msg) {
    Write-Host ""
    Write-Host "== $msg ==" -ForegroundColor Cyan
}

# ────────────────────────────────────────────────────────────────
Write-Step "pip 更新"
& $pip install --upgrade pip

# ────────────────────────────────────────────────────────────────
Write-Step "onnxruntime-gpu インストール（CPU 版と競合するため入れ替え）"
& $pip uninstall onnxruntime -y 2>$null
& $pip install "onnxruntime-gpu>=1.17.0"
Write-Host "onnxruntime-gpu: OK" -ForegroundColor Green

# ────────────────────────────────────────────────────────────────
Write-Step "PyTorch 2.6+ CUDA 12.8 インストール（Blackwell RTX 50xx 対応、約 2-3 GB）"
& $pip install --index-url https://download.pytorch.org/whl/cu128 "torch>=2.6" torchvision
Write-Host "PyTorch CUDA: OK" -ForegroundColor Green

# ────────────────────────────────────────────────────────────────
Write-Step "nvidia-ml-py インストール（GPU 監視）"
& $pip uninstall pynvml -y 2>$null   # 旧パッケージが混在していれば除去
& $pip install "nvidia-ml-py>=12.0"
Write-Host "nvidia-ml-py: OK" -ForegroundColor Green

# ────────────────────────────────────────────────────────────────
Write-Step "ngrok インストール（リモートトンネル）"
if (Get-Command ngrok -ErrorAction SilentlyContinue) {
    Write-Host "ngrok: 既にインストール済み" -ForegroundColor Green
} elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install Ngrok.Ngrok -e --accept-source-agreements --accept-package-agreements
    Write-Host "ngrok: インストール完了（PATH 反映は次回ターミナル再起動後）" -ForegroundColor Green
} else {
    Write-Warning "winget が見つかりません。https://ngrok.com/download から手動でインストールしてください。"
}

# ────────────────────────────────────────────────────────────────
# MediaPipe Pose モデルファイル自動ダウンロード
Write-Step "MediaPipe Pose モデルダウンロード"
$modelDir  = Join-Path $repoRoot "backend\cv\models"
$modelPath = Join-Path $modelDir "pose_landmarker_lite.task"
if (-not (Test-Path $modelPath)) {
    New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
    $modelUrl = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
    try {
        Invoke-WebRequest -Uri $modelUrl -OutFile $modelPath -UseBasicParsing
        Write-Host "MediaPipe モデルダウンロード完了: $modelPath" -ForegroundColor Green
    } catch {
        Write-Warning "モデルダウンロード失敗: $_"
        Write-Warning "手動でダウンロードしてください: $modelUrl"
    }
} else {
    Write-Host "MediaPipe モデル: 既存 OK" -ForegroundColor Green
}

# ────────────────────────────────────────────────────────────────
Write-Step "動作確認"
& $venvPy -c @"
import torch, onnxruntime as ort
print(f'  PyTorch CUDA available : {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'  GPU                    : {torch.cuda.get_device_name(0)}')
print(f'  ONNX providers         : {ort.get_available_providers()}')
"@

Write-Host ""
Write-Host "セットアップ完了！" -ForegroundColor Green
Write-Host "次のステップ:"
Write-Host "  start.bat でアプリを起動して設定 > GPU デバイスを確認してください。"