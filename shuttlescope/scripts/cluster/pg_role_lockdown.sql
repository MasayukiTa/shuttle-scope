-- ShuttleScope PostgreSQL role lockdown
--
-- Round 258 R40-2 (Codex addendum C-002): 本番 PostgreSQL の権限分離。
-- 現状 `ss_user` が DB OWNER + GRANT ALL を持つため、backend RCE = DB 全権限。
-- 本 SQL は role を分割し、ss_user (runtime) から危険権限を剥がす。
--
-- 実行タイミング: **手動オペレーション**。alembic 経由ではなく psql で superuser
-- (postgres ロール) として 1 回だけ実行する。
--
-- 実行前確認:
--   1. 全 backend / worker process を停止する (`pm2 stop all`)
--   2. PostgreSQL primary に postgres user で接続
--   3. 本 SQL を流す
--   4. 環境変数 SS_DB_MIGRATION_PASSWORD を新規設定 (alembic 用)
--   5. backend を再起動して既存機能 (insert/update/select/delete) が動くことを確認
--
-- 復旧 (緊急時 rollback):
--   GRANT ALL PRIVILEGES ON DATABASE shuttlescope TO ss_user;
--   GRANT ALL ON ALL TABLES IN SCHEMA public TO ss_user;
--   GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO ss_user;
--   ALTER DATABASE shuttlescope OWNER TO ss_user;
--   (ただし元の posture に戻ると security レベル下がるので最終手段)

\set ON_ERROR_STOP on

BEGIN;

-- ─── 1. ss_migration ロール作成 (DDL 専用) ──────────────────────────────────
-- パスワードは事前に環境変数で設定済みのものを使う。例:
--   \set ss_migration_password `echo $SS_DB_MIGRATION_PASSWORD`
-- もしくは psql 起動時に -v ss_migration_password='secret' で渡す。
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ss_migration') THEN
        EXECUTE format(
            'CREATE ROLE ss_migration WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEROLE NOCREATEDB INHERIT',
            current_setting('ss_migration_password', true)
        );
    END IF;
END
$$;

-- ss_migration はテーブル定義変更を行うため、所有権を移譲する。
-- ALTER TABLE OWNER は table 単位なので動的 SQL でループ。
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO ss_migration', r.tablename);
    END LOOP;
    FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER SEQUENCE public.%I OWNER TO ss_migration', r.sequencename);
    END LOOP;
END
$$;

-- ─── 2. ss_user (runtime backend role) の権限を限定 ────────────────────────
-- DROP / TRUNCATE / CREATE などの DDL を不可能にする。
-- INSERT / UPDATE / SELECT / DELETE はそのまま使えるようにする。
REVOKE ALL ON SCHEMA public FROM ss_user;
GRANT USAGE ON SCHEMA public TO ss_user;
-- CREATE 権限を SCHEMA レベルで剥奪 (新 table / function を ss_user は作れない)
REVOKE CREATE ON SCHEMA public FROM ss_user;

-- 既存 table への CRUD のみ許可。TRUNCATE/REFERENCES は剥奪。
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ss_user;
REVOKE TRUNCATE, REFERENCES ON ALL TABLES IN SCHEMA public FROM ss_user;

-- 既存 sequence への利用は許可
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO ss_user;

-- 将来 ss_migration が新規 table を作ったとき、自動で ss_user に CRUD を付与する
ALTER DEFAULT PRIVILEGES FOR ROLE ss_migration IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ss_user;
ALTER DEFAULT PRIVILEGES FOR ROLE ss_migration IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO ss_user;

-- ─── 3. access_logs テーブルを ss_user から特別扱い ────────────────────────
-- INSERT のみ許可、UPDATE/DELETE は不可。
-- PG RULE は migration 0028 で別途貼られるが、GRANT 側でも同じ縛りを入れる。
REVOKE UPDATE, DELETE ON access_logs FROM ss_user;
GRANT SELECT, INSERT ON access_logs TO ss_user;

-- ─── 4. 危険関数を全 user から剥奪 ────────────────────────────────────────
REVOKE EXECUTE ON FUNCTION pg_read_server_files(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_read_binary_file(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_ls_dir(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_read_file(text) FROM PUBLIC;

-- ─── 5. DB OWNER を ss_user から外す ──────────────────────────────────────
-- OWNER を postgres (superuser) に戻す。DB 単位の CREATE 権限も ss_user は不要。
ALTER DATABASE shuttlescope OWNER TO postgres;
REVOKE CREATE ON DATABASE shuttlescope FROM ss_user;

-- ─── 完了確認 ──────────────────────────────────────────────────────────────
-- 以下を psql で実行して期待結果が出ることを確認する:
--   \du ss_user        → Member of: (empty), Attributes: (none)
--   \du ss_migration   → Member of: (empty), Attributes: Login
--   \z access_logs     → ss_user に INSERT/SELECT のみあること
--   SELECT has_table_privilege('ss_user', 'access_logs', 'UPDATE'); → false
--   SELECT has_table_privilege('ss_user', 'access_logs', 'DELETE'); → false

COMMIT;

-- ─── 6. 環境変数の差し替え (sysadmin が手動で) ────────────────────────────
-- 新規 SS_DB_MIGRATION_URL を `.env.production` に追加:
--   SS_DB_MIGRATION_URL=postgresql+psycopg://ss_migration:<password>@127.0.0.1:5432/shuttlescope
-- alembic 実行時のみこの URL を使う:
--   set "SS_DB_MIGRATION_URL=postgresql+psycopg://ss_migration:..."
--   alembic upgrade head
-- 通常の backend / worker 起動時は引き続き ss_user の DATABASE_URL を使う。
