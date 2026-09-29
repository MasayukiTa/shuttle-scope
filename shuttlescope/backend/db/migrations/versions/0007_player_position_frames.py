"""player_position_frames テーブルを追加 (A Phase 1)

ダブルス4人＋シャトルの時系列位置データ。
YOLO追跡 / 手動 / 補間 の3ソースを統一管理する。

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-16
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "player_position_frames" not in tables:
        op.create_table(
            "player_position_frames",
            sa.Column("id",          sa.Integer(),  primary_key=True, autoincrement=True),
            sa.Column("match_id",    sa.Integer(),  sa.ForeignKey("matches.id"),  nullable=False),
            sa.Column("set_id",      sa.Integer(),  sa.ForeignKey("sets.id"),     nullable=True),
            sa.Column("rally_id",    sa.Integer(),  sa.ForeignKey("rallies.id"),  nullable=True),
            sa.Column("frame_num",   sa.Integer(),  nullable=False),
            # サイドA プレイヤー（シングルス・ダブルス共通）
            sa.Column("player_a_x",  sa.Float(),    nullable=True),
            sa.Column("player_a_y",  sa.Float(),    nullable=True),
            # サイドB プレイヤー
            sa.Column("player_b_x",  sa.Float(),    nullable=True),
            sa.Column("player_b_y",  sa.Float(),    nullable=True),
            # ダブルスパートナーA（シングルスは NULL）
            sa.Column("partner_a_x", sa.Float(),    nullable=True),
            sa.Column("partner_a_y", sa.Float(),    nullable=True),
            # ダブルスパートナーB
            sa.Column("partner_b_x", sa.Float(),    nullable=True),
            sa.Column("partner_b_y", sa.Float(),    nullable=True),
            # シャトル（検出不可は NULL）
            sa.Column("shuttle_x",   sa.Float(),    nullable=True),
            sa.Column("shuttle_y",   sa.Float(),    nullable=True),
            # データソース種別
            sa.Column("source",      sa.String(20), nullable=False, server_default="yolo_tracked"),
            sa.Column("created_at",  sa.DateTime(), nullable=False),
        )
        op.create_index("ix_ppf_match_frame", "player_position_frames", ["match_id", "frame_num"])
        op.create_index("ix_ppf_rally",       "player_position_frames", ["rally_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "player_position_frames" in tables:
        op.drop_index("ix_ppf_rally",       table_name="player_position_frames")
        op.drop_index("ix_ppf_match_frame", table_name="player_position_frames")
        op.drop_table("player_position_frames")
