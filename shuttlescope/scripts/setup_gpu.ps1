# ShuttleScope GPU セットアップスクリプト (Windows PowerShell)
# INFRA Phase A: CUDA 12.4 向け torch + mediapipe + pynvml をインストールする。
#
# 前提:
#   - .\backend\.venv\ が存在すること (setup_venv.bat で作成済み)
#   - NVIDIA ドライバ 550 以降 / CUDA 12.4 互換 GPU
#
# 使い方:
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_gpu.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $venvPy)) {
    Write-Error "venv が見つかりません: $venvPy  — 先に backend\setup_venv.bat を実行してください"
}

Write-Host "[setup_gpu] pip 更新"
& $venvPy -m pip install --upgrade pip

Write-Host "[setup_gpu] PyTorch (CUDA 12.4) インストール"
& $venvPy -m pip install --index-url https://download.pytorch.org/whl/cu124 `
    torch==2.4.* torchvision

Write-Host "[setup_gpu] MediaPipe / pynvml インストール"
& $venvPy -m pip install "mediapipe>=0.10.14" pynvml

# 任意: ONNX Runtime GPU (TrackNet ONNX 書き出し用)
Write-Host "[setup_gpu] (任意) onnxruntime-gpu"
& $venvPy -m pip install onnxruntime-gpu

# MediaPipe Pose モデルファイルの自動ダウンロード
$modelDir = Join-Path $repoRoot "backend\cv\models"
$modelPath = Join-Path $modelDir "pose_landmarker_lite.task"
if (-not (Test-Path $modelPath)) {
    Write-Host "[setup_gpu] MediaPipe Pose モデルをダウンロード中..."
    New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
    $modelUrl = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
    try {
        Invoke-WebRequest -Uri $modelUrl -OutFile $modelPath -UseBasicParsing
        Write-Host "[setup_gpu] モデルダウンロード完了: $modelPath"
    } catch {
        Write-Warning "[setup_gpu] モデルダウンロード失敗: $_"
        Write-Warning "  手動でダウンロードしてください: $modelUrl"
    }
} else {
    Write-Host "[setup_gpu] MediaPipe モデル既存: $modelPath"
}

Write-Host "[setup_gpu] 完了。以下で動作確認:"
Write-Host "  `$env:SS_USE_GPU=1; & '$venvPy' -c 'import torch; print(torch.cuda.is_available())'"
Write-Host "  `$env:SS_USE_GPU=1; & '$venvPy' -c 'from backend.cv.factory import get_tracknet; print(type(get_tracknet()).__name__)'"
