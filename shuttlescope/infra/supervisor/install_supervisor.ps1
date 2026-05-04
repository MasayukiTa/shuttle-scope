# Scheduled Task として supervisor を登録 (システム起動時自動実行)
# 対象: ShuttleScopeBackend (このタスクが backend を 24/7 監視)
$taskName = "ShuttleScopeBackend"
$daemon   = "C:\Users\kiyus\Desktop\backend_supervisor.ps1"

if (-not (Test-Path $daemon)) { Write-Host "[ERROR] supervisor script not found"; exit 1 }

# 既存タスクを削除して再登録
cmd /c "schtasks /Delete /TN $taskName /F >/dev/null 2>&1"

$tr = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$daemon`""
# /SC ONSTART = OS 起動時自動実行
# /RU でユーザー指定 (現在のログインユーザを使用)、対話セッション無くても起動
# /RL HIGHEST = 管理者権限で実行
$user = "$env:USERDOMAIN\$env:USERNAME"
Write-Host "registering task '$taskName' for user '$user' (ONSTART)..."
$out = cmd /c "schtasks /Create /TN $taskName /TR `"$tr`" /SC ONSTART /RU $user /RL HIGHEST /F 2>&1"
Write-Host "  $out"

# 確認
Write-Host "`n=== task summary ==="
cmd /c "schtasks /Query /TN $taskName /FO LIST" 2>&1 | Select-Object -First 8
