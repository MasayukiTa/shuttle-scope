"""rallies / strokes にアノテーション記録方式フィールドを追加

追加カラム:
- rallies.annotation_mode  : アノテーション記録方式 (manual_record / assisted_record)
- rallies.review_status    : レビューステータス (pending / completed)
- strokes.source_method    : 入力ソース (manual / assisted / corrected)

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-08
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect, text
    bind = op.get_bind()
    inspector = sa_inspect(bind)

    rally_cols = {c["name"] for c in inspector.get_columns("rallies")}
    stroke_cols = {c["name"] for c in inspector.get_columns("strokes")}

    # すでにカラムが存在する場合（ORM create_tables 後など）はスキップ
    if "annotation_mode" not in rally_cols:
        op.execute(text("ALTER TABLE rallies ADD COLUMN annotation_mode VARCHAR(30)"))
    if "review_status" not in rally_cols:
        op.execute(text("ALTER TABLE rallies ADD COLUMN review_status VARCHAR(20)"))
    if "source_method" not in stroke_cols:
        op.execute(text("ALTER TABLE strokes ADD COLUMN source_method VARCHAR(20)"))

    # 既存データの補完:
    # このリリース以前のラリー・ストロークは全て手動記録なので確定補完
    op.execute(text("UPDATE rallies SET annotation_mode = 'manual_record' WHERE annotation_mode IS NULL"))
    op.execute(text("UPDATE strokes SET source_method = 'manual' WHERE source_method IS NULL"))


def downgrade() -> None:
    # カラム削除の後退は不要
    pass
