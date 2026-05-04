"""R-1: サーバ集約録画アーティファクトテーブル追加。

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-29
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "server_video_artifacts" in set(inspector.get_table_names()):
        return
    op.create_table(
        "server_video_artifacts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.Integer, sa.ForeignKey("matches.id"), nullable=True),
        sa.Column("upload_id", sa.String(36), nullable=True, index=True),
        sa.Column("sender_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("finalized_at", sa.DateTime, nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("worker_synced_at", sa.DateTime, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sva_match_id", "server_video_artifacts", ["match_id"])
    op.create_index("ix_sva_started_at", "server_video_artifacts", ["started_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "server_video_artifacts" in set(inspector.get_table_names()):
        op.drop_table("server_video_artifacts")
