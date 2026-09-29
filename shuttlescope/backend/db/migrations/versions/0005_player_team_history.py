"""players テーブルに team_history カラムを追加

所属チームの変遷を JSON 配列で保持する。
形式: [{"team": "ACT SAIKYO", "until": "2025-03", "note": ""}]

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-11
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("players")]
    if "team_history" not in columns:
        op.add_column("players", sa.Column("team_history", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("players")]
    if "team_history" in columns:
        op.drop_column("players", "team_history")
