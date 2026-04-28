"""Match.video_token を追加し、既存行に UUID4 を一括バックフィルする。

video_token は /api/videos/{token}/stream の不透明キー。
これにより video_local_path を API レスポンスから除去できる。

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-28
"""
from typing import Union
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("matches")}

    # 1. nullable で列を追加
    if "video_token" not in cols:
        with op.batch_alter_table("matches") as batch:
            batch.add_column(sa.Column("video_token", sa.String(36), nullable=True))

    # 2. 既存行を UUID4 で一括バックフィル（video_token が NULL の行のみ）
    rows = bind.execute(
        sa.text("SELECT id FROM matches WHERE video_token IS NULL")
    ).fetchall()
    for r in rows:
        bind.execute(
            sa.text("UPDATE matches SET video_token = :tok WHERE id = :id"),
            {"tok": uuid.uuid4().hex, "id": r[0]},
        )

    # 3. UNIQUE インデックスを作成（NULL 値は許容、検索高速化）
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("matches")}
    if "ix_matches_video_token" not in existing_indexes:
        op.create_index(
            "ix_matches_video_token", "matches", ["video_token"], unique=True
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("matches")}
    if "ix_matches_video_token" in existing_indexes:
        op.drop_index("ix_matches_video_token", table_name="matches")
    cols = {c["name"] for c in inspector.get_columns("matches")}
    if "video_token" in cols:
        with op.batch_alter_table("matches") as batch:
            batch.drop_column("video_token")
