"""Add recordings table (match に紐づく動画。枝番 branch_no で複数 upload/live)。

試合枠を先に作成 → match_id 確定 → その match の枝番に複数動画が結びつく。

Revision ID: 0038
Revises: 0037
"""
from alembic import op
import sqlalchemy as sa


revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names()


def upgrade() -> None:
    if _has_table("recordings"):
        return
    op.create_table(
        "recordings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False, index=True),
        sa.Column("branch_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="upload"),
        sa.Column("source_kind", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("video_local_path", sa.String(length=500), nullable=True),
        sa.Column("video_token", sa.String(length=36), nullable=True),
        sa.Column("resolution", sa.String(length=20), nullable=True),
        sa.Column("fps", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("match_id", "branch_no", name="uq_recording_match_branch"),
        sa.UniqueConstraint("video_token", name="uq_recording_video_token"),
    )


def downgrade() -> None:
    if _has_table("recordings"):
        op.drop_table("recordings")
