"""Add chat_sessions / chat_messages tables (Growth Advisor chat).

coach / analyst / admin 専用の Growth Advisor チャット用永続化テーブル。
soft-delete (deleted_at) + メッセージ単位の validation_reason / is_fallback /
confidence / evidence_path / generator を保持する。

Revision ID: 0035
Revises: 0034
"""
from alembic import op
import sqlalchemy as sa


revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    if not _table_exists("chat_sessions"):
        op.create_table(
            "chat_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("role_at_creation", sa.String(32), nullable=False),
            sa.Column("lang", sa.String(8), nullable=False, server_default="ja"),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
            sa.Column("last_used_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
        op.create_index("ix_chat_sessions_last_used_at", "chat_sessions", ["last_used_at"])

    if not _table_exists("chat_messages"):
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("chat_sessions.id"), nullable=False),
            sa.Column("turn", sa.Integer(), nullable=False),
            sa.Column("author", sa.String(16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("generator", sa.String(64), nullable=True),
            sa.Column("is_fallback", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("validation_reason", sa.String(128), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("evidence_path", sa.String(256), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.current_timestamp()),
        )
        op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    try:
        op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    except Exception:
        pass
    op.drop_table("chat_messages")
    try:
        op.drop_index("ix_chat_sessions_last_used_at", table_name="chat_sessions")
        op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    except Exception:
        pass
    op.drop_table("chat_sessions")
