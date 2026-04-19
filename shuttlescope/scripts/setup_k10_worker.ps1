# K10 (GMKtec K10 / i9 13700HK / 64GB RAM) Ray ワーカー最小セットアップスクリプト
# ShuttleScope 本体をインストールせずに Ray CPU ワーカーとして参加させる。
#
# 実行方法 (K10 上の PowerShell で):
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#   .\scripts\setup_k10_worker.ps1
#
# オプション引数:
#   -PrimaryIP   <ip>   ラップトップ (head) の LAN IP (例: 192.168.1.10)
#   -WorkerDir   <path> ワーカー venv の配置先 (デフォルト: C:\ss-worker)
#   -NumCpus     <n>    Ray に公開するコア数 (デフォルト: 16)
#
param(
    [string]$PrimaryIP  = "",
    [string]$WorkerDir  = "C:\ss-worker",
    [int]   $NumCpus    = 16
)

$ErrorActionPreference = "Stop"

Write-Host "[k10-setup] === ShuttleScope K10 ワーカーセットアップ ===" -ForegroundColor Cyan

# ── 1. Python の確認 ──────────────────────────────────────────
$py = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if (-not $py) {
    Write-Host "[k10-setup] ERROR: Python が見つかりません。https://python.org からインストールしてください。" -ForegroundColor Red
    exit 1
}
$pyver = & python --version 2>&1
Write-Host "[k10-setup] Python: $py ($pyver)"

# ── 2. 仮想環境の作成 ─────────────────────────────────────────
$venvPy = "$WorkerDir\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "[k10-setup] 仮想環境を作成: $WorkerDir"
    & python -m venv $WorkerDir
} else {
    Write-Host "[k10-setup] 仮想環境は既に存在: $WorkerDir"
}

# ── 3. パッケージのインストール ───────────────────────────────
$reqFile = Join-Path $PSScriptRoot "..\requirements_worker.txt"
$reqFile = (Resolve-Path $reqFile).Path
Write-Host "[k10-setup] パッケージをインストール: $reqFile"
& "$WorkerDir\Scripts\pip" install --upgrade pip -q
& "$WorkerDir\Scripts\pip" install -r $reqFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "[k10-setup] ERROR: pip install に失敗しました。" -ForegroundColor Red
    exit 1
}
Write-Host "[k10-setup] パッケージインストール完了" -ForegroundColor Green

# ── 4. ONNX モデルファイルのコピー確認 ────────────────────────
$modelDir = "$WorkerDir\models"
$modelDst = "$modelDir\tracknet.onnx"
if (-not (Test-Path $modelDst)) {
    New-Item -ItemType Directory -Path $modelDir -Force | Out-Null
    Write-Host ""
    Write-Host "[k10-setup] tracknet.onnx が見つかりません。" -ForegroundColor Yellow
    Write-Host "            ラップトップの shuttlescope\backend\tracknet\weights\tracknet.onnx を"
    Write-Host "            次のパスにコピーしてください:"
    Write-Host "            $modelDst" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "            コピー方法の例 (ラップトップから):"
    Write-Host "            copy \\<k10-ip>\C`$\Users\... または USB 経由でコピー"
    Write-Host ""
} else {
    Write-Host "[k10-setup] tracknet.onnx 確認済み: $modelDst" -ForegroundColor Green
}

# ── 5. ワーカー起動スクリプトを生成 ──────────────────────────
$startScript = "$WorkerDir\start_worker.ps1"
$rayPort = 6379
@"
# K10 Ray ワーカー起動スクリプト（setup_k10_worker.ps1 が自動生成）
param([string]`$HeadIP = "$PrimaryIP")

if (-not `$HeadIP) {
    `$HeadIP = Read-Host "ラップトップ (head) の IP アドレスを入力してください (例: 192.168.1.10)"
}

Write-Host "[k10-worker] Ray worker を起動: head=`$HeadIP`:$rayPort"
ray stop --force 2>`$null
ray start ``
    --address="`$HeadIP`:$rayPort" ``
    --num-cpus=$NumCpus ``
    --num-gpus=0 ``
    --disable-usage-stats

Write-Host "[k10-worker] 接続完了。Ctrl+C で停止。"
"@ | Set-Content -Path $startScript -Encoding utf8

Write-Host "[k10-setup] 起動スクリプトを生成: $startScript" -ForegroundColor Green

# ── 6. セットアップ完了 ───────────────────────────────────────
Write-Host ""
Write-Host "[k10-setup] === セットアップ完了 ===" -ForegroundColor Green
Write-Host ""
Write-Host "次の手順でワーカーを起動してください:"
Write-Host ""
Write-Host "  [ラップトップ側 (プライマリ)] ShuttleScope 起動前に Ray head を開始:"
Write-Host "    scripts\cluster\start_primary.bat  -- または --"
Write-Host "    ray start --head --port=6379 --num-cpus=8 --num-gpus=1"
Write-Host ""
Write-Host "  [K10 側] Ray worker を起動:"
Write-Host "    & '$startScript' -HeadIP <ラップトップの IP>"
Write-Host ""
Write-Host "  [確認]"
Write-Host "    ray status  -- クラスタに 2 ノード表示されれば OK"
Write-Host ""
Write-Host "  [ShuttleScope 設定]"
Write-Host "    .env.development に追記: SS_CLUSTER_MODE=ray"
Write-Host "    SS_RAY_ADDRESS は 'auto' のまま（head と同一ホストから接続）"
