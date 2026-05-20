"""Add error_logs table (unhandled exception capture).

攻撃はエラーを誘発して探索してくる。グローバル例外ハンドラが拾った
スタックトレースを request_id で request_logs と相関できる形で DB に残す。

PostgreSQL: 月次 partition は不要 (件数が request_logs ほど多くない想定)。
plain table + ts index で十分。SQLite も同形。

Revision ID: 0033
Revises: 0032
"""
from alembic import op
import sqlalchemy as sa


revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    if _table_exists("error_logs"):
        return
    op.create_table(
        "error_logs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("request_id", sa.String(36), nullable=True),
        sa.Column("method", sa.String(8), nullable=True),
        sa.Column("path", sa.String(512), nullable=True),
        sa.Column("status", sa.Integer(), nullable=True),
        sa.Column("exc_type", sa.String(120), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("input_repr", sa.Text(), nullable=True),
        sa.Column("internal_code", sa.String(40), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("ip_addr", sa.String(64), nullable=True),
    )
    op.create_index("ix_el_ts", "error_logs", ["ts"])
    op.create_index("ix_el_request", "error_logs", ["request_id"])
    op.create_index("ix_el_exc", "error_logs", ["exc_type", "ts"])


def downgrade() -> None:
    op.drop_table("error_logs")
