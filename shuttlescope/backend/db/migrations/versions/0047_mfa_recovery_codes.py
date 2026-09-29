"""MFA リカバリコード表を追加。

背景 (障害):
  2026-07 に w32time (Windows Time サービス) が停止してサーバ時計がずれ、
  TOTP の検証窓 (±30 秒) を外れて admin 自身がログインできなくなった。
  当時アカウントには MFA を迂回する正規手段が一切存在せず、DB に直接接続して
  `users.totp_enabled` を落とすことでしか復旧できなかった。
  = MFA が単一障害点になっていた。

  本 migration はその復旧手段 (使い捨てリカバリコード) を永続化する。

設計:
  - 平文コードは発行時に 1 度だけ API 応答で返し、DB には SHA-256 のみ保存。
    コードは 80bit 乱数なので salt 無し高速ハッシュで安全側に十分
    (低エントロピー入力が原理的に存在しないため辞書攻撃が成立しない)。
    ハッシュ直引きにできるので、ログイン 1 回につき発行数ぶんの bcrypt を
    回す必要が無く、CPU 消費型 DoS も避けられる。
  - used_at IS NULL の行だけが有効 (単回使用)。

Revision ID: 0047
Revises: 0046
"""
from alembic import op
import sqlalchemy as sa


revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "mfa_recovery_codes" not in insp.get_table_names():
        op.create_table(
            "mfa_recovery_codes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("code_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("used_ip", sa.String(length=64), nullable=True),
        )
        op.create_index(
            "ix_mfa_recovery_codes_user_hash",
            "mfa_recovery_codes",
            ["user_id", "code_hash"],
        )

    # R47 (pg_role_lockdown) 以降、runtime role である ss_user はテーブル作成者
    # (ss_migration) が作った新規テーブルに対して ALTER DEFAULT PRIVILEGES 経由で
    # 権限を得る想定だが、その設定が入っていない環境でも確実に書けるよう明示 GRANT
    # する (0046 の partition GRANT と同じ方針)。
    # ss_user ロールが存在しない環境 (dev / SQLite / CI) では黙ってスキップする。
    if bind.dialect.name == "postgresql":
        try:
            with bind.begin_nested():
                bind.execute(
                    sa.text(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON mfa_recovery_codes TO ss_user"
                    )
                )
                bind.execute(
                    sa.text(
                        "GRANT USAGE, SELECT, UPDATE ON SEQUENCE "
                        "mfa_recovery_codes_id_seq TO ss_user"
                    )
                )
        except Exception as exc:  # noqa: BLE001 - ロール未定義環境は正常系
            print(f"[migration 0047] GRANT to ss_user skipped: {exc}")


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "mfa_recovery_codes" in insp.get_table_names():
        op.drop_index("ix_mfa_recovery_codes_user_hash", table_name="mfa_recovery_codes")
        op.drop_table("mfa_recovery_codes")
