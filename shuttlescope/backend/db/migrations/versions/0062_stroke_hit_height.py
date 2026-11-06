"""strokes.hit_height: 打球の高さ（ネット基準の4段階、任意入力）を追加する。

背景 (要望8 / SD-08)
--------------------
仙台大学との 2026-11-05 の打合せで、研究者・アナリストから次の指摘が出た:
「打点」は本来は打球の «高さ» を指す言葉で、打った人の «位置» ではない。
ところが本アプリの ``strokes.hit_zone`` は «打球時の打者の床面位置»（Zone9）で、
表示名だけが「打点 / Hit point」になっていて実態とずれていた。

この移行では、位置とは別概念である «打球の高さ» を記録する任意列を 1 本足す。
hit_zone（位置）には一切触れない。識別子も別（hit_height）にする。

値 (4 段階、ネットを基準にした相対的な高さ):
    above_net       ネットより上
    slightly_above  やや上
    slightly_below  やや下
    below           下

加算のみ (additive only)
------------------------
NULL 許容の列を 1 本追加するだけ。バックフィルはしない。既存の行はすべて
NULL（未入力）のまま残り、既存データは壊れない。NULL は「高さ未入力」を表す。

戻し方 (downgrade)
------------------
hit_height 列を落とすだけ。sqlite では batch_alter_table を使う。列を落とすと
入力済みの高さ値は失われるが、他の列・行には影響しない。

Revision ID: 0062
Revises: 0061
Create Date: 2026-11-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None

_TABLE = "strokes"
_COLUMN = "hit_height"


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    if _COLUMN not in columns:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=16), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    if _COLUMN in columns:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_column(_COLUMN)
        else:
            op.drop_column(_TABLE, _COLUMN)
