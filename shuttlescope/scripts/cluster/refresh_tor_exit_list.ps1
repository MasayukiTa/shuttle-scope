# Refresh Tor exit node IP list for cf_ban_policy.is_tor_exit().
#
# Purpose:
#   Tor exit IPs are shared by many users. Permanent-banning a Tor exit
#   blocks legitimate Tor traffic. cf_ban_policy.decide_cf_mode() downgrades
#   any IP in this file to managed_challenge regardless of confidence.
#
# Schedule:
#   Run hourly via ScheduledTask. The Tor project publishes the list at
#   https://check.torproject.org/exit-addresses and refreshes every ~30min.
#
# Format expected by backend/utils/cf_ban_policy.py:
#   ExitAddress <ip> <utc-ts>
#   (only the second token is parsed)
#
# Path matches SS_TOR_EXIT_LIST_PATH in .env.development.

param(
    [string]$OutPath = 'C:\Users\kiyus\Desktop\tor_exit_addresses.txt',
    [string]$Url     = 'https://check.torproject.org/exit-addresses',
    [int]$TimeoutSec = 30
)

$ErrorActionPreference = 'Stop'

# Atomic write via temp file to avoid partial read by the backend.
$tmp = "$OutPath.tmp"

try {
    Invoke-WebRequest -Uri $Url -OutFile $tmp -TimeoutSec $TimeoutSec -UseBasicParsing | Out-Null
    if ((Get-Item $tmp).Length -lt 100) {
        throw "downloaded file too small ($((Get-Item $tmp).Length) bytes)"
    }
    Move-Item -Force $tmp $OutPath
    $count = (Select-String -Path $OutPath -Pattern '^ExitAddress ' -SimpleMatch:$false).Count
    Write-Output "[refresh_tor_exit_list] OK $count exit IPs written to $OutPath"
} catch {
    if (Test-Path $tmp) { Remove-Item -Force $tmp }
    Write-Error "[refresh_tor_exit_list] FAILED: $($_.Exception.Message)"
    exit 1
}
