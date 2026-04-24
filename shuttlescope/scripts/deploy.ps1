<#
.SYNOPSIS
    ShuttleScope デプロイスクリプト
    git pull origin main → 起動 bat（cloudflared + backend を同時起動するもの）を叩く

.DESCRIPTION
    SSH 経由で外部から呼び出すことを想定。
    $StartBat に cloudflared と backend を同時起動する bat のフルパスを設定すること。

.EXAMPLE
    # SSH 接続後に実行（通常）
    powershell -ExecutionPolicy Bypass -File deploy.ps1

    # git pull スキップ・再起動のみ
    powershell -ExecutionPolicy Bypass -File deploy.ps1 -BackendOnly

    # ブランチ指定
    powershell -ExecutionPolicy Bypass -File deploy.ps1 -Branch feature/xxx
#>

param(
    [string]$Branch = "main",
    [switch]$BackendOnly   # git pull をスキップして再起動のみ
)

$ErrorActionPreference = "Stop"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ 設定: cloudflared + backend を同時起動する bat のパスをここに書く
#    （git 管理外の場所にある場合はフルパスで指定）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
$StartBat = ""   # 例: "C:\Users\M118A8586\shuttle_start.bat"
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

$RepoRoot = Split-Path -Parent $PSScriptRoot   # shuttlescope/ の親 = リポジトリルート
$AppRoot  = $PSScriptRoot                       # shuttlescope/
$LogFile  = Join-Path $AppRoot "deploy.log"

function Log([string]$msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Tee-Object -FilePath $LogFile -Append
}

Log "=== deploy start ==="

# ── 1. git pull ───────────────────────────────────────────────────────────────
if (-not $BackendOnly) {
    Log "git pull origin $Branch"
    Push-Location $RepoRoot
    try {
        $out = git pull origin $Branch 2>&1
        $out | ForEach-Object { Log "  git: $_" }
        if ($LASTEXITCODE -ne 0) { throw "git pull failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
} else {
    Log "BackendOnly: skipping git pull"
}

# ── 2. 起動 bat でプロセスをすべて再起動 ─────────────────────────────────────
if ($StartBat -and (Test-Path $StartBat)) {

    # bat が管理しているプロセス（cloudflared / python）を先に落とす
    Log "stopping cloudflared"
    Get-Process -Name cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force

    Log "stopping old backend"
    Get-Process -Name python -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
            if ($cmd -match "backend.main" -or $cmd -match "backend\\main.py") {
                Log "  killing PID $($_.Id)"
                Stop-Process -Id $_.Id -Force
            }
        } catch {
            Log "  (could not inspect PID $($_.Id), skipping)"
        }
    }
    Start-Sleep -Seconds 2

    # 起動 bat を非同期で実行（SSH セッションが切れても動き続けるよう detached）
    Log "launching: $StartBat"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$StartBat`"" -WindowStyle Hidden

} else {

    # $StartBat 未設定時のフォールバック: backend のみ直接起動
    $Python = Join-Path $AppRoot "backend\.venv\Scripts\python.exe"
    if (-not (Test-Path $Python)) {
        Log "ERROR: `$StartBat が未設定で venv も見つかりません ($Python)"
        Log "       deploy.ps1 の `$StartBat にパスを設定してください"
        exit 1
    }

    Log "WARNING: `$StartBat 未設定 — backend のみ直接起動します（cloudflared は再起動されません）"

    Get-Process -Name python -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
            if ($cmd -match "backend.main" -or $cmd -match "backend\\main.py") {
                Log "  killing PID $($_.Id)"
                Stop-Process -Id $_.Id -Force
            }
        } catch { }
    }
    Start-Sleep -Seconds 2

    $env:PYTHONPATH = $AppRoot
    $env:PYTHONUNBUFFERED = "1"
    $proc = Start-Process `
        -FilePath $Python `
        -ArgumentList "-m", "backend.main" `
        -WorkingDirectory $AppRoot `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput (Join-Path $AppRoot "backend.stdout.log") `
        -RedirectStandardError  (Join-Path $AppRoot "backend.stderr.log")

    Start-Sleep -Seconds 3
    if ($proc.HasExited) {
        Log "ERROR: backend exited immediately — check backend.stderr.log"
        exit 1
    }
    Log "backend started (PID $($proc.Id))"
}

# ── 3. ヘルスチェック ─────────────────────────────────────────────────────────
Log "health check"
$ok = $false
for ($i = 0; $i -lt 10; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8765/api/health" -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}

if ($ok) {
    Log "=== deploy complete: backend healthy ==="
} else {
    Log "WARNING: health check did not pass within 20s — backend may still be starting"
}
