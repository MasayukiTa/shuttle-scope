# Phase A: 3 つのセキュリティ鍵を生成して .env.development に追加するヘルパー。
#
# 既存の鍵が設定されている場合は上書きしません（誤ローテ防止）。
# 鍵を再生成したい場合は --Force を指定してください。
#
# 使い方:
#   .\scripts\generate_security_keys.ps1               # 未設定鍵のみ追記
#   .\scripts\generate_security_keys.ps1 -Force        # 既存値を上書き

param(
    [string]$EnvFile = ".\.env.development",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Write-Host "=== Phase A セキュリティ鍵生成 ===" -ForegroundColor Cyan
Write-Host "対象ファイル: $EnvFile"

# .env.development の既存内容を読み込む（なければ空）
$existing = @{}
if (Test-Path $EnvFile) {
    Get-Content $EnvFile -Encoding UTF8 | ForEach-Object {
        if ($_ -match "^([A-Z_]+)\s*=\s*(.*)$") {
            $existing[$Matches[1]] = $Matches[2]
        }
    }
}

# 鍵生成 (Python 経由)
$pythonExe = ".\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-Host "ERROR: backend venv が見つかりません: $pythonExe" -ForegroundColor Red
    Write-Host "先に backend/.venv を作成してください"
    exit 1
}

function Generate-FernetKey {
    & $pythonExe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
}
function Generate-HexKey {
    & $pythonExe -c "import secrets; print(secrets.token_hex(32))"
}

$keys = @{
    "SS_FIELD_ENCRYPTION_KEY" = { Generate-FernetKey }
    "SS_BACKUP_PASSPHRASE"    = { Generate-HexKey }
    "SS_EXPORT_SIGNING_KEY"   = { Generate-HexKey }
}

$updated = @()
foreach ($name in $keys.Keys) {
    $existingVal = $existing[$name]
    if ($existingVal -and -not $Force) {
        Write-Host "  [SKIP] $name は既に設定済み (--Force で上書き)"
        continue
    }
    $newVal = & $keys[$name]
    $existing[$name] = $newVal
    $updated += $name
    Write-Host "  [SET]  $name = $($newVal.Substring(0, 8))..." -ForegroundColor Green
}

if ($updated.Count -eq 0) {
    Write-Host "`n変更なし。" -ForegroundColor Yellow
    exit 0
}

# .env.development を再構築
$lines = @()
foreach ($k in $existing.Keys) {
    $lines += "$k=$($existing[$k])"
}
$lines | Out-File -FilePath $EnvFile -Encoding UTF8

Write-Host "`n=== 完了 ===" -ForegroundColor Green
Write-Host "更新された鍵: $($updated -join ', ')"
Write-Host "次のステップ:"
Write-Host "  1. backend を再起動 (Alembic 0016/0017 が自動適用される)"
Write-Host "  2. pip install -r backend/requirements.txt (pyzipper, hypothesis)"
Write-Host "  3. python round56.py で Phase A/B/C 検証"
Write-Host ""
Write-Host "WARNING: .env.development は git 管理外です。バックアップを別途取ってください。" -ForegroundColor Yellow
