"""access_logs に HMAC ハッシュチェーン列 (prev_hash, row_hash) を追加

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-24
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "access_logs" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("access_logs")}
    with op.batch_alter_table("access_logs") as batch:
        if "prev_hash" not in existing:
            batch.add_column(sa.Column("prev_hash", sa.String(length=64), nullable=True))
        if "row_hash" not in existing:
            batch.add_column(sa.Column("row_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "access_logs" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("access_logs")}
    with op.batch_alter_table("access_logs") as batch:
        if "row_hash" in existing:
            batch.drop_column("row_hash")
        if "prev_hash" in existing:
            batch.drop_column("prev_hash")
