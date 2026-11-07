"""(rally_id, stroke_num) に部分一意インデックスを張る

なぜ
----
`strokes` には `(rally_id, stroke_num)` の一意性が無く、インデックス
(`ix_strokes_rally_id_stroke_num`) は張ってあるだけで重複を許す。そのため:

  - `POST /api/strokes?rally_id=...` を同じラリーへ再実行 (Pass2/Pass3 の
    やり直し、オフラインキューの再送、複数端末) すると #1 / #9999 など
    同じ番号の打球が二重に入る
  - `POST /api/strokes/batch` の再送で、ラリーが重複したとき打球も重複する

重複した打球は `rally_length` と下流のカウント・系列分析を静かに壊す。
番号はラリー内の一次キーなので、DB 側で一意性を持たせる。ルータ側の
重複チェック (`deleted_at IS NULL` で絞って既存番号を探す) と同じ土俵で
効かせるため、**論理削除された行とは衝突させない部分インデックス**にする。
PostgreSQL も SQLite (3.8.0+) も部分インデックスに対応している。

一意インデックス名はモデル (`backend/db/models.py` の Stroke.__table_args__)
と同じ `uq_strokes_rally_id_stroke_num_active` にする。bootstrap の
`Base.metadata.create_all` が models から先にこの索引を作ることがあるため、
0053 / 0056..0061 と同じ idempotent パターン (存在チェックしてから create)
にする。

既存の重複について
------------------
**自動では消さない。** 打球は人が入力した一次データなので、どちらを残すかを
マイグレーションが勝手に決めてはいけない。アクティブ (deleted_at IS NULL) な
重複があれば該当行を並べて失敗する。運用側で潰してから再実行すること
(0053 rallies と同じ方針)。

Revision ID: 0062
Revises: 0061
"""
from alembic import op
import sqlalchemy as sa


revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None

_TABLE = "strokes"
_INDEX_NAME = "uq_strokes_rally_id_stroke_num_active"


def _existing_indexes(bind) -> set:
    return {ix["name"] for ix in sa.inspect(bind).get_indexes(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    if _INDEX_NAME in _existing_indexes(bind):
        return

    dupes = bind.execute(sa.text(
        "SELECT rally_id, stroke_num, COUNT(*) AS n FROM strokes "
        "WHERE deleted_at IS NULL "
        "GROUP BY rally_id, stroke_num HAVING COUNT(*) > 1 "
        "ORDER BY rally_id, stroke_num"
    )).fetchall()
    if dupes:
        detail = ", ".join(f"rally_id={r[0]} stroke_num={r[1]} x{r[2]}" for r in dupes[:20])
        more = "" if len(dupes) <= 20 else f" (\u4ed6 {len(dupes) - 20} \u7d44)"
        raise RuntimeError(
            "strokes \u306b (rally_id, stroke_num) \u306e\u91cd\u8907\u304c\u3042\u308b\u305f\u3081\u4e00\u610f\u30a4\u30f3\u30c7\u30c3\u30af\u30b9\u3092\u5f35\u308c\u307e\u305b\u3093\u3002"
            "\u3069\u3061\u3089\u3092\u6b8b\u3059\u304b\u306f\u4eba\u304c\u6c7a\u3081\u308b\u5fc5\u8981\u304c\u3042\u308b\u306e\u3067\u3001\u81ea\u52d5\u524a\u9664\u306f\u3057\u307e\u305b\u3093\u3002"
            f" \u91cd\u8907: {detail}{more}"
        )

    op.create_index(
        _INDEX_NAME,
        _TABLE,
        ["rally_id", "stroke_num"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _INDEX_NAME not in _existing_indexes(bind):
        return
    op.drop_index(_INDEX_NAME, table_name=_TABLE)
