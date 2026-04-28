# Game Day G-1: DB ファイル損失 → バックアップ復元演習
#
# 実行前に必ず確認:
#   - SS_BACKUP_PASSPHRASE が設定されていること
#   - 検証用 DB を使うこと（本番 DB を消さない）
#
# 想定手順:
#   1. 現状の DB をバックアップ作成
#   2. DB ファイル削除（損失をシミュレート）
#   3. バックアップから復元
#   4. データ整合性確認

param(
    [string]$DbPath = ".\backend\db\shuttlescope.db",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$startTime = Get-Date
Write-Host "=== Game Day G-1: DB Loss Simulation ===" -ForegroundColor Cyan
Write-Host "Start: $startTime"

if ($DryRun) {
    Write-Host "[DRY-RUN] 実際の削除は行いません" -ForegroundColor Yellow
}

# 1. バックアップ作成
Write-Host "`n[1] バックアップ作成中..."
$backupResult = & .\backend\.venv\Scripts\python -c "
from backend.services.backup_service import create_backup
p = create_backup(label='gameday_g1')
print(p)
"
Write-Host "  作成: $backupResult"

# 2. DB ファイル削除（dry-run 時はスキップ）
if (-not $DryRun) {
    Write-Host "`n[2] DB ファイルを削除中: $DbPath"
    if (Test-Path $DbPath) {
        Remove-Item $DbPath -Force
        Write-Host "  削除完了"
    } else {
        Write-Host "  存在しません（スキップ）" -ForegroundColor Yellow
    }
} else {
    Write-Host "`n[2] [DRY-RUN] DB 削除をスキップ"
}

# 3. バックアップから復元
Write-Host "`n[3] バックアップから復元中..."
& .\backend\.venv\Scripts\python -c "
from backend.services.backup_service import restore_backup
from pathlib import Path
restore_backup(Path('$backupResult'.strip()))
print('復元完了')
"

# 4. 整合性確認: テーブル件数取得
Write-Host "`n[4] 整合性確認..."
& .\backend\.venv\Scripts\python -c "
from backend.db.database import SessionLocal
from backend.db.models import Match, Player, User
with SessionLocal() as db:
    print(f'  matches: {db.query(Match).count()}')
    print(f'  players: {db.query(Player).count()}')
    print(f'  users:   {db.query(User).count()}')
"

$endTime = Get-Date
$elapsed = $endTime - $startTime
Write-Host "`n=== 完了 ===" -ForegroundColor Green
Write-Host "End:     $endTime"
Write-Host "Elapsed: $($elapsed.TotalSeconds) sec"
Write-Host "`n結果を docs/incident_response/drills/$(Get-Date -Format 'yyyy-MM')_g1_db_loss.md に記録してください"
