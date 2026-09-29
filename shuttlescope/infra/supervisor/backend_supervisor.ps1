# ShuttleScope backend supervisor
# - Scheduled Task から起動される常駐スクリプト
# - python が落ちたら自動再起動 (exponential backoff: 5/10/30/60s, 上限 5min)
# - ログ自動ローテ (10MB 超で .prev へ)
# - 12 日無人運用想定: クラッシュループ防止 + 監視ログ
$ErrorActionPreference = "Continue"
$repo    = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope"
$venvPy  = Join-Path $repo "backend\.venv\Scripts\python.exe"
$mainPy  = Join-Path $repo "backend\main.py"
$port    = $env:SS_BACKEND_PORT; if (-not $port) { $port = "8765" }
$logOut  = Join-Path $repo "backend\backend.stdout.log"
$logErr  = Join-Path $repo "backend\backend.stderr.log"
$svLog   = Join-Path $repo "backend\supervisor.log"
$rotateBytes = 10 * 1024 * 1024   # 10MB
$maxLogPrev  = 1                   # .prev 1 世代だけ保持
$backoffSec = @(5, 10, 30, 60, 120, 300)  # 連続失敗時のリトライ間隔

function Log-Sv($msg) {
  $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
  Write-Host $line
  try { Add-Content -Path $svLog -Value $line -ErrorAction Stop } catch {}
}

function Rotate-Log($path) {
  if (-not (Test-Path $path)) { return }
  $size = (Get-Item $path -ErrorAction SilentlyContinue).Length
  if ($size -ge $rotateBytes) {
    $prev = "$path.prev"
    if (Test-Path $prev) { Remove-Item $prev -Force -ErrorAction SilentlyContinue }
    try { Move-Item $path $prev -Force -ErrorAction Stop } catch {}
  }
}

function Spawn-Backend {
  Rotate-Log $logOut
  Rotate-Log $logErr

  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $venvPy
  $psi.Arguments = "`"$mainPy`""
  $psi.WorkingDirectory = $repo
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError  = $true
  $psi.RedirectStandardInput  = $true
  $psi.CreateNoWindow = $true
  $psi.Environment["API_PORT"]         = "$port"
  $psi.Environment["LAN_MODE"]         = "true"
  $psi.Environment["ENVIRONMENT"]      = "production"
  # PUBLIC_MODE=1: CORS allow_origins を tunnel host のみに絞る、
  #               TrustedHostMiddleware を有効化、docs/openapi 隠蔽、
  #               cluster/benchmark/db_maintenance router をマウント除外
  $psi.Environment["PUBLIC_MODE"]       = "1"
  $psi.Environment["HIDE_API_DOCS"]     = "1"
  $psi.Environment["HIDE_STACK_TRACES"] = "1"
  $psi.Environment["PYTHONUNBUFFERED"]  = "1"
  $psi.Environment["PYTHONUTF8"]        = "1"
  $psi.Environment["PYTHONIOENCODING"]  = "utf-8"

  $proc = New-Object System.Diagnostics.Process
  $proc.StartInfo = $psi
  $proc.EnableRaisingEvents = $true

  $null = Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -MessageData $logOut -Action {
    if ($EventArgs.Data -ne $null) { try { Add-Content -Path $event.MessageData -Value $EventArgs.Data } catch {} }
  }
  $null = Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived -MessageData $logErr -Action {
    if ($EventArgs.Data -ne $null) { try { Add-Content -Path $event.MessageData -Value $EventArgs.Data } catch {} }
  }

  [void]$proc.Start()
  $proc.BeginOutputReadLine()
  $proc.BeginErrorReadLine()
  return $proc
}

# ─── 起動済みインスタンスの check ───────────────────────────────────────
$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
  Log-Sv ("supervisor exiting: port {0} already in use by PID {1}" -f $port, $existing.OwningProcess)
  exit 0
}

Log-Sv "supervisor starting (port=$port)"

$failStreak = 0
while ($true) {
  try {
    $proc = Spawn-Backend
    Log-Sv ("spawned python PID={0}" -f $proc.Id)

    # 起動成功判定: 60s 以内に health 200 ?
    $deadline = (Get-Date).AddSeconds(60)
    $ready = $false
    while ((Get-Date) -lt $deadline -and -not $proc.HasExited) {
      try {
        $r = Invoke-WebRequest "http://127.0.0.1:$port/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
      } catch {}
      Start-Sleep 2
    }

    if (-not $ready) {
      if ($proc.HasExited) {
        Log-Sv ("python exited during startup, code={0}" -f $proc.ExitCode)
      } else {
        Log-Sv "python never reached health 200 within 60s; killing"
        try { $proc.Kill() } catch {}
        $proc.WaitForExit(5000) | Out-Null
      }
      $failStreak++
    } else {
      Log-Sv "python ready, entering long-watch mode"
      $failStreak = 0
      $proc.WaitForExit()
      Log-Sv ("python exited (code={0}) after long-watch" -f $proc.ExitCode)
    }
  } catch {
    Log-Sv ("supervisor exception: {0}" -f $_.Exception.Message)
    $failStreak++
  }

  $idx = [Math]::Min($failStreak - 1, $backoffSec.Length - 1)
  if ($idx -lt 0) { $idx = 0 }
  $sleep = $backoffSec[$idx]
  Log-Sv ("restarting in ${sleep}s (failStreak=$failStreak)")
  Start-Sleep $sleep
}
