"""Bind upload_sessions to QR/session participants.

Revision ID: 0055
Revises: 0054
"""
from alembic import op
import sqlalchemy as sa

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

_TABLE = "upload_sessions"
_COLUMN = "participant_id"
_INDEX = "ix_upload_sessions_participant_id"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns(_TABLE)}
    if _COLUMN not in columns:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Integer(), nullable=True))
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes(_TABLE)}
    if _INDEX not in indexes:
        op.create_index(_INDEX, _TABLE, [_COLUMN], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes(_TABLE)}
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name=_TABLE)
    columns = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    if _COLUMN in columns:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_column(_COLUMN)
        else:
            op.drop_column(_TABLE, _COLUMN)
