"""Phase A3: Export パッケージの nonce 重複排除テーブルを追加。

1 つの export パッケージは 1 回のみ import 可能とする (nonce 消費)。

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-28
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {t for t in inspector.get_table_names()}
    if "consumed_export_nonces" in existing:
        return
    op.create_table(
        "consumed_export_nonces",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("nonce", sa.String(32), nullable=False, unique=True, index=True),
        sa.Column("consumed_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_consumed_export_nonces_consumed_at",
        "consumed_export_nonces",
        ["consumed_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {t for t in inspector.get_table_names()}
    if "consumed_export_nonces" not in existing:
        return
    indexes = {ix["name"] for ix in inspector.get_indexes("consumed_export_nonces")}
    if "ix_consumed_export_nonces_consumed_at" in indexes:
        op.drop_index(
            "ix_consumed_export_nonces_consumed_at",
            table_name="consumed_export_nonces",
        )
    op.drop_table("consumed_export_nonces")
