"""strokes.wrist_vs_racket: official attack/defence height classification input (coach + university request).

Why this column exists
----------------------
A coach and a university group asked for the HEIGHT of the hit to be an *official*
classification rather than an ad-hoc analysis. Their agreed rule is a body-relative
one:

    wrist at or above racket height  -> attack
    wrist below racket height        -> defence

None of the existing stroke columns can express this rule directly:

- hit_height (above_net / slightly_above / slightly_below / below) is measured
  relative to the NET, not to the player's own wrist and racket.
- contact_height (overhead / side / underhand / scoop) describes the swing FORM,
  not where the wrist sits relative to the racket head.
- above_net is where the SHUTTLE was relative to the net, again not body-relative.

So a new optional column is needed to carry the raw wrist-vs-racket observation.
The attack/defence label itself is NOT stored; it is derived in one place in the
service layer (backend.analysis.attack_defence) from this column, so the rule
lives in exactly one spot.

What is added
-------------
- wrist_vs_racket : a pick-list value, one of:
      at_or_above  wrist at or above racket height  (-> attack)
      below        wrist below racket height        (-> defence)
  Optional. NULL means "not recorded" (the official classification is unknown for
  that stroke). Existing rows stay NULL, which is exactly their current meaning.

This is purely additive: no backfill, no data loss, and no change to any existing
column. Existing aggregation keeps working because it never reads this column.

Idempotent: bootstrap's Base.metadata.create_all may create this column from the
models before alembic runs, so we check for the column first (same pattern as
0056 / 0057 / 0058 / 0059 / 0060 / 0061 / 0062).

Revision ID: 0066
Revises: 0065
"""
from alembic import op
import sqlalchemy as sa

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None

_TABLE = "strokes"
_COLUMN = "wrist_vs_racket"


def _has_column(bind) -> bool:
    cols = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    return _COLUMN in cols


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=16), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_column(_COLUMN)
        else:
            op.drop_column(_TABLE, _COLUMN)
