"""Add maintenance_windows + status_incidents (ステータス/メンテ告知ページ用)。

Revision ID: 0039
Revises: 0038
"""
from alembic import op
import sqlalchemy as sa


revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def _has(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _has("maintenance_windows"):
        op.create_table(
            "maintenance_windows",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("scheduled_start", sa.DateTime(), nullable=False, index=True),
            sa.Column("scheduled_end", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    if not _has("status_incidents"):
        op.create_table(
            "status_incidents",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("severity", sa.String(length=20), nullable=False, server_default="minor"),
            sa.Column("component", sa.String(length=50), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="investigating"),
            sa.Column("began_at", sa.DateTime(), nullable=False, index=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    for t in ("status_incidents", "maintenance_windows"):
        if _has(t):
            op.drop_table(t)
