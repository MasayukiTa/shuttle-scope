$ray = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Scripts\ray.exe"
$logDir = "C:\Users\kiyus\AppData\Local\Temp\ray-head"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$out = "$logDir\ray-head.log"

# Round 258 R7 P1 fix (Codex review): Ray dashboard を既定 127.0.0.1 にする。
# `--dashboard-host=0.0.0.0` は明示 SS_RAY_EXPOSE_UNAUTH=1 のときだけ許容。
# Ray dashboard / GCS は無認証で RCE 可能なため anyone-with-network-reach 厳禁。
$dashboardHost = if ($env:SS_RAY_DASHBOARD_HOST) { $env:SS_RAY_DASHBOARD_HOST } else { '127.0.0.1' }
if ($dashboardHost -eq '0.0.0.0' -and $env:SS_RAY_EXPOSE_UNAUTH -ne '1') {
    Write-Error "FATAL: dashboard-host=0.0.0.0 requires SS_RAY_EXPOSE_UNAUTH=1. Ray dashboard/GCS are unauthenticated; exposing them on 0.0.0.0 grants RCE to anyone with network reach. Use WireGuard / Cloudflare Access / SSH tunnel instead."
    exit 2
}

# まず stop
& $ray stop --force 2>&1 | Out-Null
Start-Sleep -Seconds 2

# foreground で head 起動 (--block で永続)
& $ray start --head `
    --node-ip-address=169.254.96.137 `
    --port=6379 `
    --dashboard-host=$dashboardHost `
    --dashboard-port=8265 `
    --num-cpus=8 --num-gpus=1 `
    --disable-usage-stats `
    --block *>&1 | Tee-Object -FilePath $out
