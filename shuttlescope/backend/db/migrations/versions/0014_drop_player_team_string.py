"""Phase B-15+: players.team 文字列カラムを撤去

Player.team_id (FK→teams.id) への移行が完了したため、
互換のため残置していた Player.team (VARCHAR) を削除する。

前提:
- 全 Player の team_id が埋まっていること（NOT NULL ではないが運用上必須）
- フロント側の Player 表示が teams.name ルックアップに切替済みであること

ロールバック:
- team 文字列を再追加するが、データは復旧不可（teams.name から再生成は可能）

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-26
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("players")}
    if "team" not in cols:
        return

    # 念のため: team_id が NULL の行があれば撤去前に警告
    result = bind.execute(sa.text(
        "SELECT COUNT(*) FROM players WHERE team_id IS NULL"
    )).fetchone()
    null_count = int(result[0]) if result else 0
    if null_count > 0:
        # 失敗にはしないが、ログで通知（admin が手動 backfill していない場合の救済）
        # マイグレーション中は logger 直接使えないので print
        print(
            f"[migration 0014] WARNING: {null_count} players have NULL team_id; "
            f"team 文字列を撤去すると以後それらの所属が見えなくなる可能性があります。"
        )

    # SQLite は ALTER TABLE DROP COLUMN を 3.35 から正式対応するが、
    # alembic の SQLite 方言は batch_alter_table 経由で copy-and-move 戦略を使う
    with op.batch_alter_table("players") as batch_op:
        batch_op.drop_column("team")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("players")}
    if "team" in cols:
        return

    # 文字列カラムを復元（中身は teams.name から再生成）
    with op.batch_alter_table("players") as batch_op:
        batch_op.add_column(sa.Column("team", sa.String(100), nullable=True))

    bind.execute(sa.text(
        """
        UPDATE players
        SET team = (
            SELECT teams.name FROM teams
            WHERE teams.id = players.team_id
              AND teams.deleted_at IS NULL
        )
        WHERE team_id IS NOT NULL
        """
    ))
