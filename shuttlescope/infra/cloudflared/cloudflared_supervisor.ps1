# cloudflared 冪等スーパーバイザ。
# 既に cloudflared が動いていれば何もしない。落ちていれば起動する。
# Scheduled Task から ONSTART + 2 分間隔で呼ぶことで:
#   - reboot 後の自動起動 (ONSTART)
#   - クラッシュ時の自動復旧 (2 分以内に再起動)
# を二重起動なしで実現する。
#
# 背景: 本番の Windows service "cloudflared" は DISABLED で、起動機構が
# 存在しなかった (reboot 全断リスク)。現行のスタンドアロン運用を尊重しつつ
# 自動起動・自動復旧だけを足す。
$ErrorActionPreference = 'Continue'

$exe        = 'C:\Users\kiyus\Desktop\cf-v2\cloudflared.exe'
$cfgDir     = 'C:\Users\kiyus\Desktop\cloudflare-shuttle-scope'
$cfg        = "$cfgDir\config.yml"
$tunnelName = 'shuttlescope'
$stdoutLog  = "$cfgDir\cloudflared.stdout.log"
$stderrLog  = "$cfgDir\cloudflared.stderr.log"
$superLog   = "$cfgDir\cloudflared_supervisor.log"

function Log($m) { "$((Get-Date).ToString('o')) $m" | Out-File -FilePath $superLog -Append -Encoding utf8 }

# 既に動いていれば終了 (二重起動防止)
$proc = Get-Process cloudflared -ErrorAction SilentlyContinue
if ($proc) { exit 0 }

if (-not (Test-Path $exe)) { Log "ERROR exe missing: $exe"; exit 1 }
if (-not (Test-Path $cfg)) { Log "ERROR config missing: $cfg"; exit 1 }

Log "cloudflared not running -> starting"
Start-Process -FilePath $exe `
    -ArgumentList 'tunnel', '--config', $cfg, 'run', $tunnelName `
    -WorkingDirectory $cfgDir `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError  $stderrLog `
    -WindowStyle Hidden
Start-Sleep -Seconds 5
$p = Get-Process cloudflared -ErrorAction SilentlyContinue | Select -First 1
if ($p) { Log ("started PID=" + $p.Id) } else { Log "WARN start did not yield a process" }
