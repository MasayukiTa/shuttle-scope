-- (rally_id, stroke_num) の重複を数える。
--
-- migration 0064 (strokes に部分一意インデックス uq_strokes_rally_id_stroke_num_active
-- を張る) を本番に当てる **前** に実行すること。重複が 1 組でもあると migration は
-- RuntimeError で止まる (どちらの打球を残すかは人が決める必要があり、自動削除はしない)。
--
-- 論理削除された行 (deleted_at IS NOT NULL) は一意インデックスの対象外なので、
-- ここでも除外して「生きている重複」だけを数える。
--
-- 使い方 (PostgreSQL 本番):
--   psql "$DATABASE_URL" -f scripts/admin/count_duplicate_strokes.sql
-- 使い方 (SQLite ローカル):
--   sqlite3 backend/db/shuttlescope.db < scripts/admin/count_duplicate_strokes.sql
--
-- 0 行なら重複なし = migration をそのまま当ててよい。
-- 行が返るなら、rally_id / stroke_num ごとに重複数 n が出る。該当ラリーを開いて
-- 正しい 1 打球を残し、残りを論理削除 (deleted_at を立てる) してから migration を再実行する。

SELECT rally_id, stroke_num, COUNT(*) AS n
FROM strokes
WHERE deleted_at IS NULL
GROUP BY rally_id, stroke_num
HAVING COUNT(*) > 1
ORDER BY rally_id, stroke_num;
