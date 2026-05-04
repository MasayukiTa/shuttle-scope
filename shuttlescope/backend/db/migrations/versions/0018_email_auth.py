"""M-A2: メール認証 / パスワードリセット / 招待トークン用テーブル追加。

- users.email / users.email_verified_at 列追加
- email_verification_tokens
- password_reset_tokens
- invitation_tokens

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-28
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. users に email / email_verified_at 列を追加
    user_cols = {c["name"] for c in inspector.get_columns("users")}
    if "email" not in user_cols:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("email", sa.String(255), nullable=True))
    if "email_verified_at" not in user_cols:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("email_verified_at", sa.DateTime, nullable=True))
    user_indexes = {ix["name"] for ix in inspector.get_indexes("users")}
    if "ix_users_email" not in user_indexes:
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    existing_tables = set(inspector.get_table_names())

    # 2. email_verification_tokens
    if "email_verification_tokens" not in existing_tables:
        op.create_table(
            "email_verification_tokens",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer,
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True, index=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("expires_at", sa.DateTime, nullable=False),
            sa.Column("consumed_at", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_evt_user_id", "email_verification_tokens", ["user_id"])
        op.create_index("ix_evt_expires_at", "email_verification_tokens", ["expires_at"])

    # 3. password_reset_tokens
    if "password_reset_tokens" not in existing_tables:
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer,
                      sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True, index=True),
            sa.Column("expires_at", sa.DateTime, nullable=False),
            sa.Column("consumed_at", sa.DateTime, nullable=True),
            sa.Column("requested_ip", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_prt_user_id", "password_reset_tokens", ["user_id"])
        op.create_index("ix_prt_expires_at", "password_reset_tokens", ["expires_at"])

    # 4. invitation_tokens
    if "invitation_tokens" not in existing_tables:
        op.create_table(
            "invitation_tokens",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True, index=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("role", sa.String(20), nullable=False, server_default="analyst"),
            sa.Column("team_id", sa.Integer, sa.ForeignKey("teams.id"), nullable=True),
            sa.Column("inviter_user_id", sa.Integer,
                      sa.ForeignKey("users.id"), nullable=False),
            sa.Column("expires_at", sa.DateTime, nullable=False),
            sa.Column("consumed_at", sa.DateTime, nullable=True),
            sa.Column("consumed_by_user_id", sa.Integer,
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_invt_email", "invitation_tokens", ["email"])
        op.create_index("ix_invt_expires_at", "invitation_tokens", ["expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for t in ("invitation_tokens", "password_reset_tokens", "email_verification_tokens"):
        if t in existing_tables:
            op.drop_table(t)
    user_indexes = {ix["name"] for ix in inspector.get_indexes("users")}
    if "ix_users_email" in user_indexes:
        op.drop_index("ix_users_email", table_name="users")
    user_cols = {c["name"] for c in inspector.get_columns("users")}
    if "email_verified_at" in user_cols:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("email_verified_at")
    if "email" in user_cols:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("email")
