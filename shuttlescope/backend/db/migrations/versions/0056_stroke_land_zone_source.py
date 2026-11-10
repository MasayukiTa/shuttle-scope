"""strokes.land_zone_source: record who wrote land_zone ('cv' / 'human').

land_zone had no provenance column, so the CV auto-apply had to treat any
existing value as human input and could never refresh a value the CV itself
wrote earlier. This adds a nullable provenance column (same idea as
hit_zone_source, migration 0023).

Additive only: no backfill. Existing rows stay NULL, which keeps today's meaning
(a land_zone value with NULL source is treated as entered by a person).

Revision ID: 0056
Revises: 0055
"""
from alembic import op
import sqlalchemy as sa

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

_TABLE = "strokes"
_COLUMN = "land_zone_source"


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
