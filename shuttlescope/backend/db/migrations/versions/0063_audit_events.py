"""Add audit_events table (data-change actor tracking).

audit_events records WHO (user_id/role/ip) did WHAT (action) to WHICH entity
(entity_type/entity_id) and WHEN (ts), plus which fields changed
(changed_fields = column names only, no values), how many (field_count), and a
SHA-256 fingerprint of the change body (body_hash). Values themselves are never
stored — see backend/db/models.py AuditEvent for the rationale and measurements.

request_id correlates each row with request_logs (0032).

Revision ID: 0063
Revises: 0062
"""
from alembic import op
import sqlalchemy as sa

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None

_TABLE = "audit_events"


def _table_exists(bind, name: str) -> bool:
    return name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, _TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("ip_addr", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("changed_fields", sa.Text(), nullable=True),
        sa.Column("field_count", sa.Integer(), nullable=True),
        sa.Column("body_hash", sa.String(length=64), nullable=True),
    )
    insp = sa.inspect(bind)
    existing = {i["name"] for i in insp.get_indexes(_TABLE)}
    if "ix_audit_events_ts" not in existing:
        op.create_index("ix_audit_events_ts", _TABLE, ["ts"])
    if "ix_audit_events_user_id" not in existing:
        op.create_index("ix_audit_events_user_id", _TABLE, ["user_id"])
    if "ix_audit_events_entity" not in existing:
        op.create_index("ix_audit_events_entity", _TABLE, ["entity_type", "entity_id"])
    if "ix_audit_events_request_id" not in existing:
        op.create_index("ix_audit_events_request_id", _TABLE, ["request_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, _TABLE):
        return
    for idx in (
        "ix_audit_events_request_id",
        "ix_audit_events_entity",
        "ix_audit_events_user_id",
        "ix_audit_events_ts",
    ):
        try:
            op.drop_index(idx, table_name=_TABLE)
        except Exception:
            pass
    op.drop_table(_TABLE)
