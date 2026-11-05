"""strokes.intent_tag / intent_note: human intent memo for a shot (要望6, 仙台大 2026-11-05).

Why these columns exist
-----------------------
Researchers/analysts asked to record "what was this shot trying to do" for shots
that missed or did not score (e.g. aimed deep but caught the net). Until now a
stroke carried shot_type / zones / quality but no field for the human's guess at
the *intent*, which is exactly what later AI analysis of errors needs.

What is added
-------------
- intent_tag  : a pick-list tag normalised to a fixed vocabulary in the API layer
                (deep / net / body / sideline / cross / deception / clear_safe / other).
- intent_note : a short free-text note (<= 200 chars), optional.

Both are optional. Existing rows stay NULL, which means "no intent recorded" — the
same meaning they have had all along. This is purely additive: no backfill, no data
loss, and no change to any existing column.

Idempotent: bootstrap's Base.metadata.create_all may create these columns from the
models before alembic runs, so we check for the column first (same pattern as
0056 / 0057 / 0058 / 0059 / 0060).

Revision ID: 0061
Revises: 0060
"""
from alembic import op
import sqlalchemy as sa

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

_TABLE = "strokes"
_COLUMNS = (
    ("intent_tag", sa.String(length=20)),
    ("intent_note", sa.String(length=200)),
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    for name, coltype in _COLUMNS:
        if name not in existing:
            op.add_column(_TABLE, sa.Column(name, coltype, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    # drop in reverse order
    for name, _coltype in reversed(_COLUMNS):
        if name in existing:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table(_TABLE) as batch:
                    batch.drop_column(name)
            else:
                op.drop_column(_TABLE, name)
