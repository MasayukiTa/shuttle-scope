"""Phase B-4: players.team_id 追加 + 既存 player.team 文字列からのベスト移行

- 既存の Player.team（文字列）を teams.name と完全一致するもののみ team_id へマップ
- 一致しないものは team_id=NULL（後で admin UI から手動紐付け）
- Player.team 文字列カラムは表示用に残す（撤去は後続フェーズ）

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-26
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("players")}
    if "team_id" not in cols:
        op.add_column("players", sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=True))
        op.create_index("ix_players_team_id", "players", ["team_id"])

    # ── 既存 player.team 文字列を teams.name と一致するものに限り移行 ─────
    bind.execute(sa.text(
        """
        UPDATE players
        SET team_id = (
            SELECT teams.id FROM teams
            WHERE teams.name = players.team
              AND teams.deleted_at IS NULL
            LIMIT 1
        )
        WHERE players.team_id IS NULL
          AND players.team IS NOT NULL
          AND players.team <> ''
        """
    ))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("players")}
    if "team_id" in cols:
        try:
            op.drop_index("ix_players_team_id", table_name="players")
        except Exception:
            pass
        op.drop_column("players", "team_id")
