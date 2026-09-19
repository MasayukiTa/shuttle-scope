"""matches に player_a_start_side を足す

なぜ
----
「セット1開始時に player_a が画面のどちら側に居たか」は **試合の事実**だが、
これまで注釈者のブラウザの localStorage
(`shuttlescope.viewpoint.{matchId}`) にしか保存されていなかった。

結果:

- **CV が自分のラベルを人物に対応付けられない。** `yolo/inference.py` の
  `player_a` は「画面の上側」という意味しか持たず、それが実際にどちらの
  選手かはサーバには分からない。セット2以降のコートチェンジ以前に、
  第1セットから対応が取れていなかった
- 注釈者が別の PC を使うとコート図の向きが変わる

UI (QuickStartModal の「セット1開始時の自選手の位置」) は既にこの値を
**聞いている**。保存先が端末だっただけなので、列を足して試合に紐づける。

既存行は NULL のまま。読み手は NULL を「不明」として扱い、
従来どおり localStorage にフォールバックすること
(値を勝手に推測して埋めない — 推測した向きで CV を対応付けると、
 間違いが「サーバが言っている事実」の顔をして残る)。

Revision ID: 0054
Revises: 0053
"""
from alembic import op
import sqlalchemy as sa


revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

_TABLE = "matches"
_COLUMN = "player_a_start_side"


def _has_column(bind) -> bool:
    return any(c["name"] == _COLUMN for c in sa.inspect(bind).get_columns(_TABLE))


def upgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind):
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=10), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind):
        return
    # SQLite は 3.35 未満で DROP COLUMN を持たない。batch_alter_table なら
    # テーブル再作成で対応できる。
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
        return
    op.drop_column(_TABLE, _COLUMN)
