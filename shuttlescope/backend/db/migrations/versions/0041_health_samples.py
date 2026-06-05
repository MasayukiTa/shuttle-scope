"""Add health_samples + status_incidents.source (自動死活監視用)。

Revision ID: 0041
Revises: 0040
"""
from alembic import op
import sqlalchemy as sa


revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "health_samples" not in insp.get_table_names():
        op.create_table(
            "health_samples",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("component", sa.String(length=40), nullable=False, index=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("metric", sa.Float(), nullable=True),
            sa.Column("detail", sa.String(length=200), nullable=True),
            sa.Column("sampled_at", sa.DateTime(), nullable=False, index=True),
        )
    cols = [c["name"] for c in insp.get_columns("status_incidents")]
    if "source" not in cols:
        op.add_column(
            "status_incidents",
            sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "health_samples" in insp.get_table_names():
        op.drop_table("health_samples")
    cols = [c["name"] for c in insp.get_columns("status_incidents")]
    if "source" in cols:
        op.drop_column("status_incidents", "source")
