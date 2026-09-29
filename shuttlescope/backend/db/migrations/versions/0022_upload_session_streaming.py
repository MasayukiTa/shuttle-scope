"""R-1: upload_sessions に streaming フラグを追加。

MediaRecorder のように事前に total_size が確定しないアップロード経路で、
chunk を逐次 append し finalize 時にサイズを確定するモードを区別する。

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-29
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("upload_sessions")}
    if "streaming" not in cols:
        op.add_column(
            "upload_sessions",
            sa.Column("streaming", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("upload_sessions")}
    if "streaming" in cols:
        op.drop_column("upload_sessions", "streaming")
