"""Add users.is_test flag and protect approved real users from accidental deletion.

検証用に作成したユーザ (is_test=True) と実ユーザ (is_test=False, 保護対象) を分ける。
さらに「承認済みの実ユーザ (is_test=False かつ awaiting_admin_approval=False)」は
PostgreSQL の BEFORE DELETE トリガで誤削除を物理的に防止する。保留中ユーザ
(awaiting_admin_approval=True) は従来通り拒否(削除)できる。

正規の削除 (GDPR 等) はトランザクション内で
    SET LOCAL app.allow_protected_delete = 'on'
を設定してから DELETE すればトリガを通過する。

SQLite (local dev) では PL/pgSQL トリガを作らず、カラム追加と backfill のみ行う。

Revision ID: 0045
Revises: 0044
"""
from alembic import op
import sqlalchemy as sa


revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

_TRIGGER = "trg_protect_real_users"
_FUNC = "protect_real_users_from_delete"

_FUNC_SQL = f"""
CREATE OR REPLACE FUNCTION {_FUNC}() RETURNS trigger AS $$
BEGIN
  -- 承認済みの実ユーザ (検証用でなく、保留でもない) は明示 override なしには消せない。
  IF OLD.is_test = FALSE AND OLD.awaiting_admin_approval = FALSE THEN
    IF COALESCE(current_setting('app.allow_protected_delete', true), 'off') <> 'on' THEN
      RAISE EXCEPTION
        'Refusing to delete protected real user id=% (username=%). Set LOCAL app.allow_protected_delete=on to override.',
        OLD.id, OLD.username
        USING ERRCODE = 'raise_exception';
    END IF;
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "users" not in insp.get_table_names():
        return
    cols = [c["name"] for c in insp.get_columns("users")]

    # 1) is_test カラム追加 (default False = 実ユーザ/保護)
    if "is_test" not in cols:
        op.add_column(
            "users",
            sa.Column("is_test", sa.Boolean(), nullable=False, server_default="0"),
        )

    # 2) 既存ユーザの backfill。
    #    保護 (is_test=False): role IN (admin/analyst/demo) または id IN (2, 173)。
    #    それ以外 (player/coach/llm 等) は検証用 (is_test=True)。
    op.execute(
        sa.text(
            "UPDATE users SET is_test = :t "
            "WHERE role NOT IN ('admin','analyst','demo') AND id NOT IN (2, 173)"
        ).bindparams(t=True)
    )

    # 3) 誤削除防止トリガ (PostgreSQL のみ。SQLite は PL/pgSQL 非対応のため skip)。
    # nosemgrep 注記: PL/pgSQL のトリガ/関数生成は ORM では表現できず raw DDL が必須。
    # 以下の f-string はモジュール定数 (_TRIGGER/_FUNC/_FUNC_SQL) のみを埋め込み、
    # ユーザー入力は一切含まないため SQL インジェクションの余地はない (false positive)。
    if bind.dialect.name == "postgresql":
        op.execute(_FUNC_SQL)  # nosemgrep
        op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON users;")  # nosemgrep
        op.execute(  # nosemgrep
            f"CREATE TRIGGER {_TRIGGER} BEFORE DELETE ON users "
            f"FOR EACH ROW EXECUTE FUNCTION {_FUNC}();"
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "users" not in insp.get_table_names():
        return
    if bind.dialect.name == "postgresql":
        # 定数のみ埋め込みの raw DDL (ユーザー入力なし)。上記 upgrade と同様 false positive。
        op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON users;")  # nosemgrep
        op.execute(f"DROP FUNCTION IF EXISTS {_FUNC}();")  # nosemgrep
    cols = [c["name"] for c in insp.get_columns("users")]
    if "is_test" in cols:
        op.drop_column("users", "is_test")
