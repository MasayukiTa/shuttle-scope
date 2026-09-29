# K10 ワーカーへの動画データ差分同期スクリプト (Windows / INFRA Phase D)
#
# 優先: Cygwin/MSYS/WSL の rsync があれば rsync、無ければ robocopy (SMB 前提) にフォールバック
# 環境変数:
#   $env:K10_HOST      : 例 k10.local
#   $env:K10_USER      : 例 ss
#   $env:SS_VIDEO_ROOT : ローカル動画ルート
#   $env:K10_REMOTE_ROOT: リモート側 (rsync 時) もしくは UNC パス (robocopy 時)

$ErrorActionPreference = "Stop"

foreach ($v in @("K10_HOST", "K10_USER", "SS_VIDEO_ROOT")) {
    if (-not (Test-Path "Env:$v")) {
        Write-Error "$v が未設定です"
        exit 1
    }
}

$Src = $env:SS_VIDEO_ROOT
$LogDir = if ($env:SS_LOG_DIR) { $env:SS_LOG_DIR } else { ".\logs" }
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "sync_videos_to_k10_$Stamp.log"

$RsyncCmd = Get-Command rsync -ErrorAction SilentlyContinue
if ($RsyncCmd) {
    $RemoteRoot = if ($env:K10_REMOTE_ROOT) { $env:K10_REMOTE_ROOT } else { "/home/$($env:K10_USER)/shuttlescope/videos" }
    $Dest = "$($env:K10_USER)@$($env:K10_HOST):$RemoteRoot/"
    Write-Host "[sync] rsync from=$Src to=$Dest"
    & rsync -avh --partial --progress --delete-after `
        -e "ssh -o StrictHostKeyChecking=accept-new" `
        "$Src/" "$Dest" 2>&1 | Tee-Object -FilePath $LogFile -Append
} else {
    # rsync 非対応時: UNC 共有前提で robocopy
    if (-not $env:K10_REMOTE_ROOT) {
        Write-Error "rsync が無い場合 K10_REMOTE_ROOT に UNC パス (例 \\k10\videos) を設定してください"
        exit 1
    }
    $Dest = $env:K10_REMOTE_ROOT
    Write-Host "[sync] robocopy from=$Src to=$Dest"
    & robocopy $Src $Dest /MIR /Z /R:2 /W:5 /NFL /NDL /NP /LOG+:$LogFile
}

Write-Host "[sync] done -> $LogFile"
