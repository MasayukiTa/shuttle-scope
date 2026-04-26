"""Phase B-14: matches.owner_team_id を NOT NULL 化

0009 で全既存試合は testチーム へ owner 割当済み。安全のためマイグレーション
内で残存 NULL を再度 testチームへ吸収してから NOT NULL 制約を付与する。
SQLite は ALTER COLUMN を直接サポートしないため batch_alter_table を使用する
（テーブル再作成）。Postgres では SQL レベルの ALTER で完結する。

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-26
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "matches" not in inspector.get_table_names():
        return
    cols = {c["name"]: c for c in inspector.get_columns("matches")}
    if "owner_team_id" not in cols:
        # 0009 を未適用の環境では何もしない
        return

    # ── 残存 NULL を testチームに吸収 ─────────────────────────────────────────
    test_team = bind.execute(
        sa.text("SELECT id FROM teams WHERE display_id = :d"), {"d": "TEST-0001"}
    ).fetchone()
    if test_team:
        bind.execute(
            sa.text("UPDATE matches SET owner_team_id = :tid WHERE owner_team_id IS NULL"),
            {"tid": test_team[0]},
        )

    # まだ NULL が残るなら NOT NULL 化は失敗するので明示的にチェック
    null_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM matches WHERE owner_team_id IS NULL")
    ).scalar()
    if null_count and null_count > 0:
        raise RuntimeError(
            f"matches.owner_team_id に NULL 行が残っています ({null_count} 件)。"
            "testチーム（display_id=TEST-0001）が存在するか、admin が事前に "
            "全試合の owner_team_id を割り当てているか確認してください。"
        )

    # 既に NOT NULL ならスキップ
    if not cols["owner_team_id"].get("nullable", True):
        return

    dialect = bind.dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("matches", recreate="always") as batch_op:
            batch_op.alter_column(
                "owner_team_id",
                existing_type=sa.Integer(),
                nullable=False,
            )
    else:
        op.alter_column(
            "matches",
            "owner_team_id",
            existing_type=sa.Integer(),
            nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "matches" not in inspector.get_table_names():
        return
    cols = {c["name"]: c for c in inspector.get_columns("matches")}
    if "owner_team_id" not in cols:
        return

    dialect = bind.dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("matches", recreate="always") as batch_op:
            batch_op.alter_column(
                "owner_team_id",
                existing_type=sa.Integer(),
                nullable=True,
            )
    else:
        op.alter_column(
            "matches",
            "owner_team_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
