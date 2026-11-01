"""matches.is_demo_public - explicit marker that a demo-team match may be shown read-only to other teams (g26b / audit #587 / demo public pool)

Why this column exists
----------------------
Audit item #587 and the "demo public pool" decision (terra, A options, approved
2026-10-31) asked that the match list and the public pool may reveal a match to
users of *other* teams only when the match belongs to the demo team AND carries
an explicit, persisted demo marker. We implement this fail closed: a new boolean
`is_demo_public` that defaults to False. Every pre-existing row is therefore
treated as NOT demo-public, so nothing becomes visible to other teams by this
change. The visibility decision is made by one shared helper
(backend.utils.auth.match_is_demo_public) used by every read path (list, detail,
video, derived analysis). This marker is independent of `is_public_pool`
(the admin-set general public pool) and must never be set on a real match.

Additive only: one NOT NULL column with a server default; no data loss.

Revision ID: 0059
Revises: 0058
"""
from alembic import op
import sqlalchemy as sa

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

_TABLE = "matches"
_COLUMN = "is_demo_public"
_INDEX = "ix_matches_is_demo_public"


def upgrade() -> None:
    # bootstrap では Base.metadata.create_all が models からこの列を先に作ることが
    # あるため、alembic でも二重作成にならないよう存在チェックしてから add_column する
    # (0051 / 0056 / 0057 / 0058 と同じ idempotent パターン)。
    insp = sa.inspect(op.get_bind())
    existing = {c["name"] for c in insp.get_columns(_TABLE)}
    if _COLUMN not in existing:
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # 既存行 (create_all 経路で NULL が残り得る) を明示的に False へ寄せる。
    op.execute(
        sa.text(
            f"UPDATE {_TABLE} SET {_COLUMN} = false WHERE {_COLUMN} IS NULL"
        )
    )

    existing_indexes = {i["name"] for i in insp.get_indexes(_TABLE)}
    if _INDEX not in existing_indexes:
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _INDEX in {i["name"] for i in insp.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in {c["name"] for c in insp.get_columns(_TABLE)}:
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_column(_COLUMN)
        else:
            op.drop_column(_TABLE, _COLUMN)
