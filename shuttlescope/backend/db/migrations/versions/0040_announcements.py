"""Add announcements (公開更新情報/お知らせ フィード)。

Revision ID: 0040
Revises: 0039
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def _has(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has("announcements"):
        return
    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="published"),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    # 公開可の初回 launch エントリのみ seed (内部 CHANGELOG は公開しない)。
    now = datetime.utcnow()
    op.bulk_insert(
        sa.table(
            "announcements",
            sa.column("title", sa.String),
            sa.column("body", sa.Text),
            sa.column("status", sa.String),
            sa.column("pinned", sa.Boolean),
            sa.column("published_at", sa.DateTime),
            sa.column("created_at", sa.DateTime),
            sa.column("updated_at", sa.DateTime),
        ),
        [{
            "title": "公開ステータスページを開設しました",
            "body": "サーバの稼働状況・予定メンテナンス・障害情報をこのページで確認できるようになりました。"
                    "今後の更新情報もこちらに掲載します。",
            "status": "published",
            "pinned": False,
            "published_at": now,
            "created_at": now,
            "updated_at": now,
        }],
    )


def downgrade() -> None:
    if _has("announcements"):
        op.drop_table("announcements")
