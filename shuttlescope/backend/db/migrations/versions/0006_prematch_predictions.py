"""prematch_predictions テーブルを追加

試合前統計予測スナップショット。
試合日以前のデータのみで算出し、一度保存したら再計算しない。

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-12
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "prematch_predictions" not in tables:
        op.create_table(
            "prematch_predictions",
            sa.Column("id",                   sa.Integer(),     primary_key=True, autoincrement=True),
            sa.Column("match_id",             sa.Integer(),     sa.ForeignKey("matches.id"),  nullable=False),
            sa.Column("player_id",            sa.Integer(),     sa.ForeignKey("players.id"), nullable=False),
            sa.Column("opponent_id",          sa.Integer(),     sa.ForeignKey("players.id"), nullable=False),
            sa.Column("cutoff_date",          sa.Date(),        nullable=False),
            sa.Column("tournament_level",     sa.String(20),    nullable=False),
            sa.Column("sample_size",          sa.Integer(),     nullable=False, server_default="0"),
            sa.Column("h2h_count",            sa.Integer(),     nullable=False, server_default="0"),
            sa.Column("win_probability",      sa.Float(),       nullable=True),
            sa.Column("set_distribution",     sa.Text(),        nullable=True),
            sa.Column("most_likely_scorelines", sa.Text(),      nullable=True),
            sa.Column("score_volatility",     sa.Text(),        nullable=True),
            sa.Column("confidence",           sa.Float(),       nullable=True),
            sa.Column("match_narrative",      sa.Text(),        nullable=True),
            sa.Column("computed_at",          sa.DateTime(),    nullable=False),
        )
        op.create_index("ix_pp_match_player", "prematch_predictions", ["match_id", "player_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "prematch_predictions" in tables:
        op.drop_index("ix_pp_match_player", table_name="prematch_predictions")
        op.drop_table("prematch_predictions")
