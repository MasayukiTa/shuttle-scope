# Ray head 冪等スーパーバイザ。
# 6379 が listen していなければ RayHead Scheduled Task をトリガーする。
# Scheduled Task (ONSTART + 2 分巡回) から呼ぶことで、backend 生存中に Ray head
# だけ落ちたケースも自動復旧する (backend_supervisor のフックは backend 起動時のみ)。
#
# 禁則: 直接 `ray start` は絶対にしない (SSH/job-object 連動 kill・過去8回再現)。
# 必ず Start-ScheduledTask 経由 (SYSTEM, detached)。
$ErrorActionPreference = 'Continue'
$superLog = 'C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope\backend\ray_supervisor.log'
function Log($m) { "$((Get-Date).ToString('o')) $m" | Out-File -FilePath $superLog -Append -Encoding utf8 }

$up = Get-NetTCPConnection -LocalPort 6379 -State Listen -ErrorAction SilentlyContinue
if ($up) { exit 0 }   # 既に稼働 → no-op

$task = Get-ScheduledTask -TaskName 'RayHead' -ErrorAction SilentlyContinue
if (-not $task) { Log 'RayHead task not found - skip'; exit 1 }

Log 'ray head down (6379) -> triggering RayHead scheduled task'
Start-ScheduledTask -TaskName 'RayHead'
Start-Sleep -Seconds 15
$now = Get-NetTCPConnection -LocalPort 6379 -State Listen -ErrorAction SilentlyContinue
if ($now) { Log 'ray head recovered' } else { Log 'WARN ray head still down after trigger' }
