"""Add `category` to public_inquiries (R42: ban appeal channel).

Round 258 R42:
  - Honeytoken / canary 検知で自動 ban された IP が「これは誤 ban」と申し立てる
    導線を入れる。新カテゴリ "ban_appeal" を分類するため public_inquiries に
    `category` 列を追加する。
  - 既存行は "general" として埋める (default)。
  - SQLite / PostgreSQL 両対応。冪等。

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("public_inquiries")}
    if "category" not in cols:
        with op.batch_alter_table("public_inquiries") as batch:
            batch.add_column(
                sa.Column(
                    "category",
                    sa.String(length=40),
                    nullable=False,
                    server_default="general",
                )
            )
        # 既存行は既に server_default で埋まる
        op.create_index(
            "ix_public_inquiries_category",
            "public_inquiries",
            ["category"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    idxs = {i["name"] for i in inspector.get_indexes("public_inquiries")}
    if "ix_public_inquiries_category" in idxs:
        op.drop_index("ix_public_inquiries_category", table_name="public_inquiries")
    cols = {c["name"] for c in inspector.get_columns("public_inquiries")}
    if "category" in cols:
        with op.batch_alter_table("public_inquiries") as batch:
            batch.drop_column("category")
