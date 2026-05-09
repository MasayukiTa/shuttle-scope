# Scheduled Task として supervisor を登録 (システム起動時自動実行)
# 対象: ShuttleScopeBackend (このタスクが backend を 24/7 監視)
#
# Round 258 R12 P0 fix (NEW-1): 旧コードは daemon path を user の Desktop に固定
# していた (`C:\Users\kiyus\Desktop\backend_supervisor.ps1`)。Desktop は user-writable
# なので、低権限 malware が同 user 文脈で動けば script を差し替え、次回 OS 再起動
# 時に **管理者権限 (RL HIGHEST) で任意コード実行** が成立する LPE 経路だった。
# 対策:
#   1. supervisor script を %ProgramData%\ShuttleScope\ (admin-only writable) に配置
#   2. 登録前に icacls で「Authenticated Users 読み専用 / 書込みは Administrators のみ」を強制
#   3. daemon path が user-writable な場所を指していたら登録拒否
$taskName = "ShuttleScopeBackend"
$secureRoot = "C:\ProgramData\ShuttleScope"
$daemon = Join-Path $secureRoot "backend_supervisor.ps1"

if (-not (Test-Path $secureRoot)) {
    New-Item -ItemType Directory -Path $secureRoot -Force | Out-Null
    # ACL: Administrators / SYSTEM のみ書込み可、Users は読み取り
    icacls $secureRoot /inheritance:r /grant:r "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F" "Users:(OI)(CI)RX" 2>&1 | Out-Null
}

if (-not (Test-Path $daemon)) {
    Write-Host "[ERROR] supervisor script not found at $daemon"
    Write-Host "        Copy the script to $secureRoot first (ACL: Admin write only)."
    exit 1
}

# Daemon path が user-writable な場所を指していないか防御的に確認
$daemonResolved = (Resolve-Path $daemon).Path
$forbiddenPrefixes = @(
    [Environment]::GetFolderPath('Desktop'),
    [Environment]::GetFolderPath('UserProfile'),
    "$env:LOCALAPPDATA",
    "$env:APPDATA",
    "$env:TEMP"
)
foreach ($p in $forbiddenPrefixes) {
    if ($p -and $daemonResolved.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "[FATAL] daemon path '$daemonResolved' resides under user-writable '$p'."
        Write-Host "        That allows local privilege escalation when /RL HIGHEST is used."
        Write-Host "        Move the script to $secureRoot."
        exit 2
    }
}

# 既存タスクを削除して再登録
# Round 258 R20 P3 fix (R18a-3 P3-3): 旧コードは POSIX 形式 `>/dev/null 2>&1` を
# cmd /c に渡していた。cmd.exe ではこの形式は無効で実際には redirect されていない
# (`>` でファイル名 `/dev/null` への redirect 試行 → ENOENT で stderr に消化不良
# メッセージ)。Windows 形式 `>nul 2>&1` に修正。
cmd /c "schtasks /Delete /TN $taskName /F >nul 2>&1"

$tr = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$daemon`""
# /SC ONSTART = OS 起動時自動実行
# /RU でユーザー指定 (現在のログインユーザを使用)、対話セッション無くても起動
# /RL HIGHEST = 管理者権限で実行
$user = "$env:USERDOMAIN\$env:USERNAME"
Write-Host "registering task '$taskName' for user '$user' (ONSTART) -> $daemonResolved ..."
$out = cmd /c "schtasks /Create /TN $taskName /TR `"$tr`" /SC ONSTART /RU $user /RL HIGHEST /F 2>&1"
Write-Host "  $out"

# 確認
Write-Host "`n=== task summary ==="
cmd /c "schtasks /Query /TN $taskName /FO LIST" 2>&1 | Select-Object -First 8
