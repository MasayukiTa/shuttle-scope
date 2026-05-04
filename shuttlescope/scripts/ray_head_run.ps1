$ray = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\.venv\Scripts\ray.exe"
$logDir = "C:\Users\kiyus\AppData\Local\Temp\ray-head"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$out = "$logDir\ray-head.log"
$err = "$logDir\ray-head.err"

# 縺ｾ縺・stop
& $ray stop --force 2>&1 | Out-Null
Start-Sleep -Seconds 2

# foreground 縺ｧ head 襍ｷ蜍・(--block 縺ｧ豌ｸ邯・
& $ray start --head `
    --node-ip-address=169.254.96.137 `
    --port=6379 `
    --dashboard-host=0.0.0.0 `
    --dashboard-port=8265 `
    --num-cpus=8 --num-gpus=1 `
    --disable-usage-stats `
    --block *>&1 | Tee-Object -FilePath $out
