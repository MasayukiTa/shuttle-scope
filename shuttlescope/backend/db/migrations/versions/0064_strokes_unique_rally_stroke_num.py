"""(rally_id, stroke_num) に部分一意インデックスを張る

なぜ
----
`strokes` には `(rally_id, stroke_num)` の一意性が無い。Index
(ix_strokes_rally_id_stroke_num) はあるが一意ではないため:

  - 同じラリーに Pass2 を再実行すると、別キーの POST で #1 / #9999 が二重に入る
  - レスポンス喪失後の自動再送・複数端末・オフラインキューの巻き戻しで同じ
    stroke_num が二重に入る

重複した打球は rally_length と下流の全カウントを静かにずらす。stroke_num は
ラリー内の順序キーなので、DB 側で一意性を持たせる。

論理削除 (`deleted_at`) された行とは衝突させたくないので **部分インデックス**
にする。PostgreSQL も SQLite (3.8.0+) も部分インデックスに対応している。
rallies の 0053 (uq_rallies_set_id_rally_num_active) と同じ思想・同じ形。

既存の重複について
------------------
**本番の既存データに重複があると、このインデックス作成は失敗する。**
打球は人が入力した一次データなので、どちらを残すかをマイグレーションが勝手に
決めてはいけない。**重複があれば該当行を並べて RuntimeError で止める。**
運用側で潰してから再実行すること。

重複を事前に数えるには、migration を当てる前に次の SQL を実行する
(scripts/admin/count_duplicate_strokes.sql と同じ内容):

    SELECT rally_id, stroke_num, COUNT(*) AS n
    FROM strokes
    WHERE deleted_at IS NULL
    GROUP BY rally_id, stroke_num
    HAVING COUNT(*) > 1
    ORDER BY rally_id, stroke_num;

Revision ID: 0064
Revises: 0063
"""
from alembic import op
import sqlalchemy as sa


revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None

_INDEX_NAME = "uq_strokes_rally_id_stroke_num_active"


def _existing_indexes(bind) -> set:
    return {ix["name"] for ix in sa.inspect(bind).get_indexes("strokes")}


def upgrade() -> None:
    bind = op.get_bind()
    if _INDEX_NAME in _existing_indexes(bind):
        return

    # 本番の既存データに (rally_id, stroke_num) の重複があると一意インデックスは
    # 張れない。自動では消さず、該当を並べて止める。
    dupes = bind.execute(sa.text(
        "SELECT rally_id, stroke_num, COUNT(*) AS n FROM strokes "
        "WHERE deleted_at IS NULL "
        "GROUP BY rally_id, stroke_num HAVING COUNT(*) > 1 "
        "ORDER BY rally_id, stroke_num"
    )).fetchall()
    if dupes:
        detail = ", ".join(f"rally_id={r[0]} stroke_num={r[1]} x{r[2]}" for r in dupes[:20])
        more = "" if len(dupes) <= 20 else f" (他 {len(dupes) - 20} 組)"
        raise RuntimeError(
            "strokes に (rally_id, stroke_num) の重複があるため一意インデックスを張れません。"
            "どちらを残すかは人が決める必要があるので、自動削除はしません。"
            f" 重複: {detail}{more}"
        )

    op.create_index(
        _INDEX_NAME,
        "strokes",
        ["rally_id", "stroke_num"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    if _INDEX_NAME not in _existing_indexes(op.get_bind()):
        return
    op.drop_index(_INDEX_NAME, table_name="strokes")
