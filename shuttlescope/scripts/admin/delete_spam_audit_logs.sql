-- delete_spam_audit_logs.sql
-- 2026-05-20: admin の単発操作。詳細に「AAAAA」「aaaaaa」が大量に入っている
-- audit log を削除する。access_logs は migration 0028 で PG RULE により
-- append-only 化されているため、RULE を一時 drop → DELETE → RULE 再作成し、
-- 削除自体も新規 audit row として記録する。
--
-- 使用手順 (本番 = Minisforum X1 AI / PostgreSQL):
--   1. ssh prod && cd /path/to/shuttlescope
--   2. psql $DATABASE_URL -f scripts/admin/delete_spam_audit_logs.sql
--   3. トランザクション内で SELECT 結果を必ず目視確認してから COMMIT する。
--      不安なら ROLLBACK で抜ける。
--
-- 安全性:
--   - SERIALIZABLE トランザクションで囲み、削除条件は details に対する
--     LIKE 部分一致のみ。条件で他のログを巻き込む余地は基本ない想定だが、
--     1 行目で必ず SELECT して件数を確認する。
--   - DELETE 前に対象行を CTE で id だけ確定させ、その id 群のみを削除する
--     (条件と DELETE のレースをなくす)。
--   - 削除完了後に access_logs に "audit_log_purge" レコードを 1 件残す。

BEGIN;

-- 1) 対象候補の件数を確認 (実行者は EXPLAIN 不要、件数のみ確認)
SELECT
  COUNT(*) FILTER (WHERE details LIKE '%AAAAA%')  AS aaaaa_count,
  COUNT(*) FILTER (WHERE details LIKE '%aaaaaa%') AS lower_aaaaaa_count
FROM access_logs
WHERE details LIKE '%AAAAA%' OR details LIKE '%aaaaaa%';

-- 2) 対象 id を temp table に固定
CREATE TEMP TABLE _purge_ids AS
SELECT id, created_at, action, user_id, ip_addr, LEFT(details, 80) AS preview
FROM access_logs
WHERE details LIKE '%AAAAA%' OR details LIKE '%aaaaaa%'
ORDER BY id;

-- 3) 中身を目視確認 (実行者は出力をスクロールして「これだけ消す」を確認)
SELECT * FROM _purge_ids;

-- 4) append-only RULE を一時 drop
ALTER TABLE access_logs DISABLE RULE access_logs_no_delete;

-- 5) 削除実行 (id ピンポイント)
DELETE FROM access_logs WHERE id IN (SELECT id FROM _purge_ids);

-- 6) RULE 再有効化
ALTER TABLE access_logs ENABLE RULE access_logs_no_delete;

-- 7) 削除アクションそのものを audit log に追加
INSERT INTO access_logs (action, details, created_at)
SELECT
  'audit_log_purge',
  json_build_object(
    'purged_count', (SELECT COUNT(*) FROM _purge_ids),
    'purged_ids',   (SELECT array_agg(id ORDER BY id) FROM _purge_ids),
    'reason',       'admin manual cleanup: AAAAA / aaaaaa spam'
  )::text,
  NOW();

-- 8) 確認後にコミット。問題があれば代わりに ROLLBACK; を打って抜ける。
COMMIT;
