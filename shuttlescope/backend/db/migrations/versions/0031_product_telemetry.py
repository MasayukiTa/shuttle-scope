"""Product telemetry + DOB / minor capture flag.

Adds:
  - `product_events` table (high-density event log; partitioned by month on
    PostgreSQL; plain table on SQLite for dev)
  - `users.date_of_birth` NULLABLE — basis for minor flag
  - `matches.captured_minor_flag` NULLABLE — True if any participant player
    was a minor on `matches.date`; default NULL (unknown)
  - `tutorial_completion` table — replayable tutorials, per-user state

Retention policy: raw events are NOT deleted. PostgreSQL uses monthly RANGE
partitions on `server_ts` for query locality; older partitions can be moved
to a slower tablespace later but never dropped.

Revision ID: 0031
Revises: 0030
"""
from alembic import op
import sqlalchemy as sa


revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    # 1. users.date_of_birth (NULLABLE) ─────────────────────────────────────
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("date_of_birth", sa.Date(), nullable=True))

    # 2. matches.captured_minor_flag (NULLABLE) ─────────────────────────────
    with op.batch_alter_table("matches") as batch:
        batch.add_column(sa.Column("captured_minor_flag", sa.Boolean(), nullable=True))

    # 3. tutorial_completion ────────────────────────────────────────────────
    op.create_table(
        "tutorial_completion",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tutorial_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"),  # in_progress / completed / skipped
        sa.Column("last_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("replay_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "tutorial_id", name="uq_tutorial_user_tut"),
    )
    op.create_index("ix_tutorial_completion_user", "tutorial_completion", ["user_id"])

    # 4. product_events ─────────────────────────────────────────────────────
    # PostgreSQL: native RANGE partition on server_ts (monthly).
    # SQLite: plain table (dev only; we don't run prod telemetry on SQLite).
    if _is_postgres():
        op.execute(
            """
            CREATE TABLE product_events (
              event_id UUID NOT NULL,
              user_id_hash CHAR(64),
              team_id_hash CHAR(64),
              role VARCHAR(20),
              event_type VARCHAR(40) NOT NULL,
              props JSONB NOT NULL DEFAULT '{}'::jsonb,
              client_ts TIMESTAMPTZ NOT NULL,
              server_ts TIMESTAMPTZ NOT NULL DEFAULT now(),
              app_version VARCHAR(40),
              platform VARCHAR(20),
              PRIMARY KEY (event_id, server_ts)
            ) PARTITION BY RANGE (server_ts);
            """
        )
        # 当月パーティション + 翌月パーティションを即作成（worker が以降月次で追加）
        op.execute(
            """
            DO $$
            DECLARE
              cur DATE := date_trunc('month', now())::date;
              nxt DATE := (date_trunc('month', now()) + interval '1 month')::date;
              nxt2 DATE := (date_trunc('month', now()) + interval '2 months')::date;
              pname_cur TEXT := 'product_events_' || to_char(cur, 'YYYY_MM');
              pname_nxt TEXT := 'product_events_' || to_char(nxt, 'YYYY_MM');
            BEGIN
              EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF product_events FOR VALUES FROM (%L) TO (%L)',
                pname_cur, cur, nxt
              );
              EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF product_events FOR VALUES FROM (%L) TO (%L)',
                pname_nxt, nxt, nxt2
              );
            END $$;
            """
        )
        op.execute("CREATE INDEX IF NOT EXISTS ix_pe_type_ts ON product_events (event_type, server_ts DESC);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_pe_user_ts ON product_events (user_id_hash, server_ts DESC);")
        op.execute("CREATE INDEX IF NOT EXISTS ix_pe_props ON product_events USING GIN (props jsonb_path_ops);")
    else:
        # SQLite (dev) — single plain table, JSONB → TEXT
        op.create_table(
            "product_events",
            sa.Column("event_id", sa.String(36), primary_key=True),
            sa.Column("user_id_hash", sa.String(64), nullable=True),
            sa.Column("team_id_hash", sa.String(64), nullable=True),
            sa.Column("role", sa.String(20), nullable=True),
            sa.Column("event_type", sa.String(40), nullable=False),
            sa.Column("props", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("client_ts", sa.DateTime(), nullable=False),
            sa.Column("server_ts", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("app_version", sa.String(40), nullable=True),
            sa.Column("platform", sa.String(20), nullable=True),
        )
        op.create_index("ix_pe_type_ts", "product_events", ["event_type", "server_ts"])
        op.create_index("ix_pe_user_ts", "product_events", ["user_id_hash", "server_ts"])


def downgrade() -> None:
    op.drop_index("ix_pe_user_ts", table_name="product_events")
    op.drop_index("ix_pe_type_ts", table_name="product_events")
    if _is_postgres():
        op.execute("DROP INDEX IF EXISTS ix_pe_props;")
    op.drop_table("product_events")
    op.drop_index("ix_tutorial_completion_user", table_name="tutorial_completion")
    op.drop_table("tutorial_completion")
    with op.batch_alter_table("matches") as batch:
        batch.drop_column("captured_minor_flag")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("date_of_birth")
