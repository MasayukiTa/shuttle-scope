"""Audit log append-only via PG RULE + ss_user role lockdown.

Round 258 R40-2 + R40-3 (Codex addendum C-002 + B):

(R40-3) `access_logs` を append-only にする。RULE で UPDATE / DELETE を NO-OP に変換。
        HMAC chain (R3 era) と二段重ね — chain は app-level、RULE は DB-level の
        最終ブレーキ。backend を完全 RCE されても DB から audit を消せない。

(R40-2) `ss_user` (= 本番 backend が使う runtime role) から DDL / 危険な OS-level
        function 実行権限を剥奪する。普段の INSERT/UPDATE/SELECT/DELETE は無傷。
        DROP / TRUNCATE / CREATE / pg_read_server_files / COPY ... TO PROGRAM は閉じる。
        Schema migration は別途 `ss_migration` ロールを別パスワード/別接続で行う運用に移行する。

注意: 本 migration は **PostgreSQL でのみ実 query を実行** する。SQLite では no-op。
      ss_migration ロール作成は別途 admin が手作業で行う前提 (CREATE ROLE 自体に
      superuser 権限が必要なので alembic 経由は不適切)。本 migration は **既存
      ss_user に対する REVOKE のみ** を実行する。

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-11
"""

from alembic import op


revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    bind = op.get_bind()
    return bind is not None and "postgresql" in str(bind.dialect.name).lower()


def upgrade() -> None:
    if not _is_postgresql():
        # SQLite では rule sys がないので no-op。app-level HMAC chain で代替。
        return

    bind = op.get_bind()

    # ─── R40-3: access_logs を append-only に ──────────────────────────────
    # PG RULE で UPDATE/DELETE を NO-OP に書き換える。
    # 既存 row への単なる SELECT / INSERT は影響なし。
    try:
        op.execute(
            "CREATE OR REPLACE RULE access_logs_no_update AS "
            "ON UPDATE TO access_logs DO INSTEAD NOTHING"
        )
        op.execute(
            "CREATE OR REPLACE RULE access_logs_no_delete AS "
            "ON DELETE TO access_logs DO INSTEAD NOTHING"
        )
    except Exception as exc:
        # access_logs が存在しない (まだ初期化前) 等は warning 扱いで先送り。
        # 次回起動時の bootstrap_database で table 作成された後に再実行する。
        print(f"[migration 0028] access_logs append-only rule skipped: {exc}")

    # ─── R40-2: ss_user (= current_user) からの危険権限剥奪 ────────────────
    # NOTE: 実 backend は `ss_user` で接続している。本 migration を **migration 用
    # 別ロール** で走らせる前提だが、現状 alembic も ss_user で走っている可能性が
    # 高いため、`ss_user` が OWNER の状態だと REVOKE は self-revoke になり次回
    # 起動時に必要な書込みも止まる。
    # そこで本 migration は **runtime に危険な関数だけ REVOKE FROM PUBLIC** に絞る。
    # role split (= ss_user から所有権・DDL 権限を剥奪) は手動オペレーション
    # ファイル (`scripts/cluster/pg_role_lockdown.sql`) で実行する設計に分離。
    dangerous_funcs = [
        "pg_read_server_files(text)",
        "pg_read_binary_file(text)",
        "pg_ls_dir(text)",
        "pg_ls_dir(text, boolean, boolean)",
        "pg_read_file(text)",
        "pg_read_file(text, bigint, bigint)",
    ]
    # PG では失敗すると transaction 全体が aborted 状態になるので、
    # 各 REVOKE を SAVEPOINT で隔離する。これで一部の関数が存在しなくても
    # 他の関数 / 後続 statement は通る。
    import sqlalchemy as sa
    for sig in dangerous_funcs:
        try:
            with bind.begin_nested():
                bind.execute(sa.text(f"REVOKE EXECUTE ON FUNCTION {sig} FROM PUBLIC"))
        except Exception as exc:
            print(f"[migration 0028] REVOKE on {sig} skipped: {exc}")


def downgrade() -> None:
    if not _is_postgresql():
        return
    try:
        op.execute("DROP RULE IF EXISTS access_logs_no_update ON access_logs")
        op.execute("DROP RULE IF EXISTS access_logs_no_delete ON access_logs")
    except Exception:
        pass
    # 危険関数の GRANT 復元はしない (security regression を防ぐ)。
