"""Add request_logs.source to distinguish backend vs nginx-origin rows.

backend RequestLogMiddleware は FastAPI 到達リクエストを source='backend' で
記録する。nginx access ログ全体を取り込むと、proxy されたリクエストは backend
行と nginx 行の 2 つになるため、source 列で区別する:
  - 'backend': FastAPI 到達 (user_id 付き、アプリ視点)
  - 'nginx'  : nginx エッジ視点 (実 bytes / nginx 応答時間 / ブロック分含む)

Revision ID: 0034
Revises: 0033
"""
from alembic import op
import sqlalchemy as sa


revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def _col_exists(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    if _col_exists("request_logs", "source"):
        return
    # 既存行は backend 由来とみなす
    op.add_column(
        "request_logs",
        sa.Column("source", sa.String(10), nullable=False, server_default="backend"),
    )
    op.create_index("ix_rl_source_ts", "request_logs", ["source", "ts"])


def downgrade() -> None:
    try:
        op.drop_index("ix_rl_source_ts", table_name="request_logs")
    except Exception:
        pass
    op.drop_column("request_logs", "source")
