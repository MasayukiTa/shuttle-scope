# ShuttleScope: request_logs / product_events の月次パーティションを先行作成する。
# ensure_partitions.py は SS_DB_MIGRATION_URL を os.environ から読むが、
# 独立スケジュールタスクにはサービス env が渡らないため、ここで .env.development から
# 該当行を読み込んで環境変数として子プロセスへ渡す。
$ErrorActionPreference = "Stop"
$base = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope"
$envFile = Join-Path $base ".env.development"
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*SS_DB_MIGRATION_URL\s*=\s*(.+?)\s*$') {
        $val = $matches[1].Trim('"').Trim("'")
        $env:SS_DB_MIGRATION_URL = $val
    }
}
if (-not $env:SS_DB_MIGRATION_URL) { Write-Error "SS_DB_MIGRATION_URL not found in .env.development"; exit 2 }
$py = Join-Path $base "backend\.venv\Scripts\python.exe"
& $py (Join-Path $base "backend\tools\ensure_partitions.py")
exit $LASTEXITCODE
