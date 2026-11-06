"""matches.result_source — mark whether result/final_score were entered by a human or auto-filled (G6 item #524)

Why this column exists
----------------------
Item #524 decided option A: when the finished sets decide a match (2-0 / 2-1),
`end_set` fills `matches.result` and `matches.final_score` automatically, in the
same transaction as the set save. Manually entered values must never be
overwritten. To tell the two apart we persist the source of the current
result/final_score:

  - 'manual' : entered by a person (match create / edit, early finish, walkover).
               Auto-fill must never touch a row whose source is 'manual'.
  - 'auto'   : filled by end_set from the completed sets. Auto-fill may recompute
               and overwrite an 'auto' row (idempotent, safe to re-run).

All existing rows predate auto-fill and are therefore treated as manual: the
column is NOT NULL with server_default 'manual', and this migration also writes
'manual' into any row left NULL (bootstrap path where the column was created by
create_all before this migration ran).

Additive only: one NOT NULL column with a server default; no data loss.

Revision ID: 0058
Revises: 0057
"""
from alembic import op
import sqlalchemy as sa

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None

_TABLE = "matches"
_COLUMN = "result_source"


def upgrade() -> None:
    # bootstrap 経路は Base.metadata.create_all で models どおりの表を先に作ってから
    # alembic を回すため、この列が既に存在し得る。素の add_column だと
    # "duplicate column name" で migration 全体が失敗する (0051 / 0056 / 0057 と同じ理由)。
    # 存在確認してから足す。
    insp = sa.inspect(op.get_bind())
    existing = {c["name"] for c in insp.get_columns(_TABLE)}
    if _COLUMN not in existing:
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.String(length=10),
                nullable=False,
                server_default="manual",
            ),
        )

    # 既存行 (create_all で列だけ先に出来て NULL のケースを含む) を manual に揃える。
    # 新規 add_column の行は server_default で既に 'manual'。ここは冪等。
    op.execute(
        sa.text(
            f"UPDATE {_TABLE} SET {_COLUMN} = 'manual' WHERE {_COLUMN} IS NULL"
        )
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _COLUMN in {c["name"] for c in insp.get_columns(_TABLE)}:
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_column(_COLUMN)
        else:
            op.drop_column(_TABLE, _COLUMN)
