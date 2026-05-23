"""Add current_scope JSON column on chat_sessions.

会話駆動スコープ (period / shot_type / zone など) をターン跨ぎで保持するための
セッション側カラム。NULL 可、デフォルト NULL。

Revision ID: 0037
Revises: 0036
"""
from alembic import op
import sqlalchemy as sa


revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def _has_column(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("chat_sessions", "current_scope"):
        op.add_column(
            "chat_sessions",
            sa.Column("current_scope", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch:
        try:
            batch.drop_column("current_scope")
        except Exception:
            pass
