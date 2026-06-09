"""Add announcements.title_en / body_en (公開ステータスの更新情報の英語版)。

Revision ID: 0044
Revises: 0043
"""
from alembic import op
import sqlalchemy as sa


revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "announcements" not in insp.get_table_names():
        return
    cols = [c["name"] for c in insp.get_columns("announcements")]
    if "title_en" not in cols:
        op.add_column("announcements", sa.Column("title_en", sa.String(length=200), nullable=True))
    if "body_en" not in cols:
        op.add_column("announcements", sa.Column("body_en", sa.Text(), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "announcements" not in insp.get_table_names():
        return
    cols = [c["name"] for c in insp.get_columns("announcements")]
    if "body_en" in cols:
        op.drop_column("announcements", "body_en")
    if "title_en" in cols:
        op.drop_column("announcements", "title_en")
