"""Phase B-7: 派生レコードに team_id 列を追加

公開プール試合（is_public_pool=True）を複数チームが個別解析できるよう、
コメント・専門ラベル・ブックマーク・予測等の「書き込み主体に紐づく派生」は
team_id で分離する。

対象テーブル:
- comments
- expert_labels
- event_bookmarks
- human_forecasts
- pre_match_observations
- prematch_predictions
- clip_cache

各テーブルへ team_id (FK→teams.id, nullable) を追加。既存行は NULL のまま。
NULL は B-1 以前の移行データで「全チーム可視（互換）」扱い。
新規書き込みは router 側で ctx.team_id を必須注入する。

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-26
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels = None
depends_on = None


_TARGET_TABLES = (
    "comments",
    "expert_labels",
    "event_bookmarks",
    "human_forecasts",
    "pre_match_observations",
    "prematch_predictions",
    "clip_cache",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    for tbl in _TARGET_TABLES:
        if tbl not in table_names:
            continue
        cols = {c["name"] for c in inspector.get_columns(tbl)}
        if "team_id" not in cols:
            op.add_column(
                tbl,
                sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=True),
            )
            try:
                op.create_index(f"ix_{tbl}_team_id", tbl, ["team_id"])
            except Exception:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    for tbl in _TARGET_TABLES:
        if tbl not in table_names:
            continue
        cols = {c["name"] for c in inspector.get_columns(tbl)}
        if "team_id" in cols:
            try:
                op.drop_index(f"ix_{tbl}_team_id", table_name=tbl)
            except Exception:
                pass
            try:
                op.drop_column(tbl, "team_id")
            except Exception:
                pass
