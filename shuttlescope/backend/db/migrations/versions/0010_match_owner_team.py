"""Phase B-3: matches に owner_team_id / is_public_pool / home/away_team_id 追加

- 既存試合は testチーム (display_id=TEST-0001) へ一括移行
- owner_team_id は最終的に NOT NULL 化したいが、本マイグレーションでは
  既存全行を testチームへセットしたうえで NOT NULL 制約を付与する
- is_public_pool は admin が「全チーム共有」設定時のみ True
- home_team_id / away_team_id は試合参加チーム（owner とは別軸）

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-26
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("matches")}

    # ── 列追加 ───────────────────────────────────────────────────────────────
    # SQLite で ADD COLUMN with FK は batch_alter_table が必要
    with op.batch_alter_table("matches") as batch_op:
        if "owner_team_id" not in cols:
            batch_op.add_column(
                sa.Column(
                    "owner_team_id",
                    sa.Integer(),
                    sa.ForeignKey("teams.id", name="fk_matches_owner_team_id_teams"),
                    nullable=True,
                )
            )
        if "is_public_pool" not in cols:
            batch_op.add_column(sa.Column("is_public_pool", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        if "home_team_id" not in cols:
            batch_op.add_column(
                sa.Column(
                    "home_team_id",
                    sa.Integer(),
                    sa.ForeignKey("teams.id", name="fk_matches_home_team_id_teams"),
                    nullable=True,
                )
            )
        if "away_team_id" not in cols:
            batch_op.add_column(
                sa.Column(
                    "away_team_id",
                    sa.Integer(),
                    sa.ForeignKey("teams.id", name="fk_matches_away_team_id_teams"),
                    nullable=True,
                )
            )

    # ── 既存試合を testチームへ一括割当 ─────────────────────────────────────
    test_team = bind.execute(sa.text("SELECT id FROM teams WHERE display_id = :d"), {"d": "TEST-0001"}).fetchone()
    if test_team:
        team_id = test_team[0]
        bind.execute(
            sa.text("UPDATE matches SET owner_team_id = :tid WHERE owner_team_id IS NULL"),
            {"tid": team_id},
        )

    # ── インデックス ─────────────────────────────────────────────────────────
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("matches")}
    if "ix_matches_owner_team_id" not in existing_indexes:
        op.create_index("ix_matches_owner_team_id", "matches", ["owner_team_id"])
    if "ix_matches_is_public_pool" not in existing_indexes:
        op.create_index("ix_matches_is_public_pool", "matches", ["is_public_pool"])

    # NOTE: 本マイグレーションでは NOT NULL 化はしない。
    # SQLite の ALTER COLUMN は制限が大きいため、すべての試合に owner が
    # 割り当てられたことを admin UI で確認後、別マイグレーションで NOT NULL 化する。


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("matches")}
    indexes = {ix["name"] for ix in inspector.get_indexes("matches")}

    for ix_name in ("ix_matches_owner_team_id", "ix_matches_is_public_pool"):
        if ix_name in indexes:
            try:
                op.drop_index(ix_name, table_name="matches")
            except Exception:
                pass

    for col in ("away_team_id", "home_team_id", "is_public_pool", "owner_team_id"):
        if col in cols:
            try:
                op.drop_column("matches", col)
            except Exception:
                pass
