"""(set_id, rally_num) に部分一意インデックスを張る

なぜ
----
`rallies` には `(set_id, rally_num)` の一意性が無い。そのため:

  - 途中まで入力した試合を開き直すと、クライアントが rally_num を 1 から
    振り直して既存番号に重ねる (モバイル注釈は既存ラリーを取得できておらず
    常に 1 から始まっていた — `GET /rallies/match/{id}` 追加前)
  - 複数端末・再送・オフラインキューの巻き戻しで同じ番号が二重に入る

重複したラリーはスコア推移も集計も静かに壊す。番号は入力の一次キーなので、
DB 側で一意性を持たせる。

論理削除 (`deleted_at`) された行とは衝突させたくないので **部分インデックス**
にする。PostgreSQL も SQLite (3.8.0+) も部分インデックスに対応している。

既存の重複について
------------------
**自動では消さない。** ラリーは人が入力した一次データなので、どちらを残すかを
マイグレーションが勝手に決めてはいけない。重複があれば該当行を並べて失敗する。
運用側で潰してから再実行すること。

Revision ID: 0053
Revises: 0052
"""
from alembic import op
import sqlalchemy as sa


revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

_INDEX_NAME = "uq_rallies_set_id_rally_num_active"


def _existing_indexes(bind) -> set:
    return {ix["name"] for ix in sa.inspect(bind).get_indexes("rallies")}


def upgrade() -> None:
    bind = op.get_bind()
    if _INDEX_NAME in _existing_indexes(bind):
        return

    dupes = bind.execute(sa.text(
        "SELECT set_id, rally_num, COUNT(*) AS n FROM rallies "
        "WHERE deleted_at IS NULL "
        "GROUP BY set_id, rally_num HAVING COUNT(*) > 1 "
        "ORDER BY set_id, rally_num"
    )).fetchall()
    if dupes:
        detail = ", ".join(f"set_id={r[0]} rally_num={r[1]} x{r[2]}" for r in dupes[:20])
        more = "" if len(dupes) <= 20 else f" (他 {len(dupes) - 20} 組)"
        raise RuntimeError(
            "rallies に (set_id, rally_num) の重複があるため一意インデックスを張れません。"
            "どちらを残すかは人が決める必要があるので、自動削除はしません。"
            f" 重複: {detail}{more}"
        )

    op.create_index(
        _INDEX_NAME,
        "rallies",
        ["set_id", "rally_num"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    if _INDEX_NAME not in _existing_indexes(op.get_bind()):
        return
    op.drop_index(_INDEX_NAME, table_name="rallies")
