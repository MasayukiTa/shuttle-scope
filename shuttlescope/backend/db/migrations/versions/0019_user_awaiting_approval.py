"""User.awaiting_admin_approval 列追加。

公開 register 経由の自己作成ユーザを admin 承認まで全 API 403 にするためのフラグ。

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-29
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "awaiting_admin_approval" not in cols:
        with op.batch_alter_table("users") as batch:
            batch.add_column(
                sa.Column(
                    "awaiting_admin_approval",
                    sa.Boolean,
                    nullable=False,
                    server_default=sa.text("FALSE"),
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "awaiting_admin_approval" in cols:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("awaiting_admin_approval")
