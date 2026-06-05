"""Add llm_conversations + llm_turns (汎用 LLM チャット /#/llm 用)。

Revision ID: 0042
Revises: 0041

新規テーブルのみ (既存テーブルの ALTER 無し) なので所有権の問題は起きない。
"""
from alembic import op
import sqlalchemy as sa


revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    names = insp.get_table_names()
    if "llm_conversations" not in names:
        op.create_table(
            "llm_conversations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("title", sa.String(length=200), nullable=False, server_default="新しいチャット"),
            sa.Column("provider", sa.String(length=40), nullable=True),
            sa.Column("model", sa.String(length=120), nullable=True),
            sa.Column("system_prompt", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True, index=True),
            sa.Column("last_used_at", sa.DateTime(), nullable=True, index=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
    if "llm_turns" not in names:
        op.create_table(
            "llm_turns",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("llm_conversations.id"), nullable=False, index=True),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("tool_calls", sa.JSON(), nullable=True),
            sa.Column("tokens", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True, index=True),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    names = insp.get_table_names()
    if "llm_turns" in names:
        op.drop_table("llm_turns")
    if "llm_conversations" in names:
        op.drop_table("llm_conversations")
