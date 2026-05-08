"""GDPR / APPI: user_consents 同意取得記録テーブル。

GDPR Article 7(1) (demonstrate consent) / APPI 第18条 (利用目的の明示) 準拠。
4 種同意 (service_delivery / ai_training / research_participation /
cross_border_transfer / beta_agreement) を 1 行 1 件で記録し、
時系列で give / withdraw を追跡する。

加えて users.consent_required (既存ユーザ救済 flag) を追加する。
新規ユーザは常に consent_required=True で作成され、初回ログイン時に
同意画面を経由しない限り保護対象 endpoint へアクセスできない。
既存ユーザは consent_required=False で migration 時に設定し、
次回ログイン時に同意画面誘導 (frontend 側で強制) する。

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-08
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── user_consents テーブル新設 ────────────────────────────────────────
    if "user_consents" not in inspector.get_table_names():
        op.create_table(
            "user_consents",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("consent_type", sa.String(length=50), nullable=False),
            sa.Column("consent_given", sa.Boolean(), nullable=False),
            sa.Column("privacy_policy_version", sa.String(length=20), nullable=False),
            sa.Column("terms_version", sa.String(length=20), nullable=False),
            sa.Column(
                "given_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
            ),
            sa.Column("withdrawn_at", sa.DateTime(), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent_hash", sa.String(length=128), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index(
            "idx_user_consents_user_type",
            "user_consents",
            ["user_id", "consent_type"],
        )

    # ── users.consent_required (既存ユーザ救済 flag) ─────────────────────
    user_cols = {c["name"] for c in inspector.get_columns("users")}
    if "consent_required" not in user_cols:
        # SQLite と PostgreSQL の両方で boolean リテラルを解釈できるよう
        # sa.text("true") を使う (PG は integer リテラルを boolean 列に
        # 使えない、SQLite は true/false 双方を 1/0 として受け付ける)。
        op.add_column(
            "users",
            sa.Column(
                "consent_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
        # 既存ユーザは consent_required=false に設定 (次回ログイン時に同意画面誘導)。
        # 新規ユーザは default true で作成され、必ず onboarding 経路を通る。
        op.execute("UPDATE users SET consent_required = false")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_cols = {c["name"] for c in inspector.get_columns("users")}
    if "consent_required" in user_cols:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("consent_required")

    if "user_consents" in inspector.get_table_names():
        op.drop_index("idx_user_consents_user_type", table_name="user_consents")
        op.drop_table("user_consents")
