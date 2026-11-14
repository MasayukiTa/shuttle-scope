"""players に height_cm 列を足す (任意・nullable の身長)

なぜ
----
将来のペア編成 / 身体差の解析 (例: 小柄の選手 2 人の超攻撃ペア) は、データが
蓄積してから可能になる。そのときに選手の身長が必要になるので、今のうちに
捕捉できる器 (任意入力の列) だけを用意しておく。解析そのものはここでは作らない。

height_cm は nullable Integer。既存行は NULL のまま (未入力扱い)。体組成 (Condition.weight_kg 等)
とは別系統で、選手プロフィールの基本属性として team スコープ内でのみ扱う。
冪等: 列が既にあれば何もしない。

Revision ID: 0066
Revises: 0065
"""
from alembic import op
import sqlalchemy as sa


revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None

_TABLE = "players"
_COLUMN = "height_cm"


def _has_column(bind) -> bool:
    cols = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    return _COLUMN in cols


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind):
        op.drop_column(_TABLE, _COLUMN)
