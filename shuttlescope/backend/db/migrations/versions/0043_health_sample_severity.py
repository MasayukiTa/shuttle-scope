"""Add health_samples.severity (連続グラデーション用の深刻度 [0,1])。

Revision ID: 0043
Revises: 0042
"""
from alembic import op
import sqlalchemy as sa


revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "health_samples" not in insp.get_table_names():
        return
    cols = [c["name"] for c in insp.get_columns("health_samples")]
    if "severity" not in cols:
        op.add_column("health_samples", sa.Column("severity", sa.Float(), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "health_samples" not in insp.get_table_names():
        return
    cols = [c["name"] for c in insp.get_columns("health_samples")]
    if "severity" in cols:
        op.drop_column("health_samples", "severity")
