"""Phase A: strokes に hit_zone_source / hit_zone_cv_original を追加。

打点 (hit_zone) を CV 自動推定値そのまま使ったか、人間が override したかを
記録する。データ品質計測 + CV モデル改善のフィードバックループに使う。

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-04
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("strokes")}
    if "hit_zone_source" not in cols:
        op.add_column(
            "strokes",
            sa.Column("hit_zone_source", sa.String(length=10), nullable=True),
        )
    if "hit_zone_cv_original" not in cols:
        op.add_column(
            "strokes",
            sa.Column("hit_zone_cv_original", sa.String(length=5), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("strokes")}
    if "hit_zone_cv_original" in cols:
        op.drop_column("strokes", "hit_zone_cv_original")
    if "hit_zone_source" in cols:
        op.drop_column("strokes", "hit_zone_source")
