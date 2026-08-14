# ShuttleScope: PostgreSQL の古いログを削除する (日次スケジュールタスクから実行)。
#
# 背景 (障害):
#   2026-07 に request_logs のパーティションが欠損し、INSERT が失敗するたびに
#   PostgreSQL が ERROR 行を書いた結果、data\log が 2.5GB/日 × 24 日 = 57GB まで
#   膨張した。原因 (migration 0046) は解消済みで現在は約 0.08MB/日 だが、
#   log_truncate_on_rotation=off + 日付ファイル名のためログは無限に溜まり続ける。
#   次に別のエラーが多発すれば同じ規模で再発する。
#
# SSD 配慮: 削除のみ行う。圧縮・アーカイブ・移動といった追加書き込みはしない。
$ErrorActionPreference = "Stop"
$base = "C:\Users\kiyus\Desktop\github\shuttle-scope\shuttlescope"
$py = Join-Path $base "backend\.venv\Scripts\python.exe"
$script = Join-Path $base "backend\tools\pg_log_cleanup.py"
& $py $script
exit $LASTEXITCODE
