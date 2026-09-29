"""ShotTypeAnnotation テーブル追加（AI 学習用ショット種別アノテーション）

admin 権限者のみが書き込む shot_type_annotations テーブルを作成する。
stroke_id ごとに 1 件（UPSERT 対象）。

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-27
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {t for t in inspector.get_table_names()}
    if "shot_type_annotations" in existing:
        return

    op.create_table(
        "shot_type_annotations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.Integer, sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("stroke_id", sa.Integer, sa.ForeignKey("strokes.id"), nullable=False),
        sa.Column("shot_type", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Integer, nullable=False, server_default="2"),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("annotator_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("stroke_id", name="uq_shot_type_annotation_stroke"),
    )
    op.create_index("ix_shot_type_annotations_match_id",  "shot_type_annotations", ["match_id"])
    op.create_index("ix_shot_type_annotations_stroke_id", "shot_type_annotations", ["stroke_id"])
    op.create_index("ix_shot_type_annotations_user_id",   "shot_type_annotations", ["annotator_user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {t for t in inspector.get_table_names()}
    if "shot_type_annotations" not in existing:
        return

    op.drop_index("ix_shot_type_annotations_user_id",   "shot_type_annotations")
    op.drop_index("ix_shot_type_annotations_stroke_id",  "shot_type_annotations")
    op.drop_index("ix_shot_type_annotations_match_id",   "shot_type_annotations")
    op.drop_table("shot_type_annotations")
