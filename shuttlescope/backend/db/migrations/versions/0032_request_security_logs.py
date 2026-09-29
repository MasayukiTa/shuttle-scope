"""Add request_logs (HTTP-level) and security_events tables.

External attack observability that access_logs (internal-action chain) does
not cover:
  - request_logs: per-HTTP-request row (ts ms, IP, XFF, method, path, query,
    UA, status, response_time_ms, user_id, request_id) — 攻撃か正常アクセス
    かを判別するための一次ソース。PostgreSQL では月次 RANGE partition
    (migration 0031 と同じパターン) で読み出しコストを抑える。SQLite (dev)
    は plain table。
  - security_events: 専門的な攻撃検知イベント。rate_limit_hit, probe_attempt
    (/.env, /wp-admin 等の探索), honeytoken_hit, ip_ban, path_normalization_block
    などを単独行で記録。access_logs と違って HMAC chain を付けない
    (高頻度書き込みでチェーン lock の競合が出るため)。

Retention: request_logs は 90 日以降のパーティションを cold storage 想定 (後で
worker 拡張)。security_events は重要なので長期保持。

Revision ID: 0032
Revises: 0031
"""
from alembic import op
import sqlalchemy as sa


revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    # ─── request_logs ────────────────────────────────────────────────
    if not _table_exists("request_logs"):
        if _is_postgres():
            op.execute(
                """
                CREATE TABLE request_logs (
                  id            BIGSERIAL,
                  ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
                  duration_ms   INTEGER     NOT NULL DEFAULT 0,
                  method        VARCHAR(8)  NOT NULL,
                  path          VARCHAR(512) NOT NULL,
                  query         VARCHAR(1024),
                  status        SMALLINT    NOT NULL,
                  user_id       INTEGER,
                  ip_addr       VARCHAR(64),
                  xff           VARCHAR(255),
                  ua            VARCHAR(255),
                  referer       VARCHAR(255),
                  request_id    VARCHAR(36),
                  bytes_in      INTEGER,
                  bytes_out     INTEGER,
                  cf_ray        VARCHAR(32),
                  country       CHAR(2),
                  PRIMARY KEY (id, ts)
                ) PARTITION BY RANGE (ts);
                """
            )
            # 当月 + 翌月パーティションを即作成
            op.execute(
                """
                DO $$
                DECLARE
                  cur DATE := date_trunc('month', now())::date;
                  nxt DATE := (date_trunc('month', now()) + interval '1 month')::date;
                  nxt2 DATE := (date_trunc('month', now()) + interval '2 months')::date;
                  pname_cur TEXT := 'request_logs_' || to_char(cur, 'YYYY_MM');
                  pname_nxt TEXT := 'request_logs_' || to_char(nxt, 'YYYY_MM');
                BEGIN
                  EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS %I PARTITION OF request_logs FOR VALUES FROM (%L) TO (%L)',
                    pname_cur, cur, nxt
                  );
                  EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS %I PARTITION OF request_logs FOR VALUES FROM (%L) TO (%L)',
                    pname_nxt, nxt, nxt2
                  );
                END $$;
                """
            )
            op.execute("CREATE INDEX IF NOT EXISTS ix_rl_ts        ON request_logs (ts DESC);")
            op.execute("CREATE INDEX IF NOT EXISTS ix_rl_user_ts   ON request_logs (user_id, ts DESC) WHERE user_id IS NOT NULL;")
            op.execute("CREATE INDEX IF NOT EXISTS ix_rl_ip_ts     ON request_logs (ip_addr, ts DESC);")
            op.execute("CREATE INDEX IF NOT EXISTS ix_rl_status_ts ON request_logs (status, ts DESC) WHERE status >= 400;")
            op.execute("CREATE INDEX IF NOT EXISTS ix_rl_path_ts   ON request_logs (path varchar_pattern_ops, ts DESC);")
            op.execute("CREATE INDEX IF NOT EXISTS ix_rl_request   ON request_logs (request_id);")
        else:
            op.create_table(
                "request_logs",
                sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                sa.Column("ts", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
                sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
                sa.Column("method", sa.String(8), nullable=False),
                sa.Column("path", sa.String(512), nullable=False),
                sa.Column("query", sa.String(1024), nullable=True),
                sa.Column("status", sa.Integer(), nullable=False),
                sa.Column("user_id", sa.Integer(), nullable=True),
                sa.Column("ip_addr", sa.String(64), nullable=True),
                sa.Column("xff", sa.String(255), nullable=True),
                sa.Column("ua", sa.String(255), nullable=True),
                sa.Column("referer", sa.String(255), nullable=True),
                sa.Column("request_id", sa.String(36), nullable=True),
                sa.Column("bytes_in", sa.Integer(), nullable=True),
                sa.Column("bytes_out", sa.Integer(), nullable=True),
                sa.Column("cf_ray", sa.String(32), nullable=True),
                sa.Column("country", sa.String(2), nullable=True),
            )
            op.create_index("ix_rl_ts", "request_logs", ["ts"])
            op.create_index("ix_rl_user_ts", "request_logs", ["user_id", "ts"])
            op.create_index("ix_rl_ip_ts", "request_logs", ["ip_addr", "ts"])
            op.create_index("ix_rl_status_ts", "request_logs", ["status", "ts"])
            op.create_index("ix_rl_path_ts", "request_logs", ["path"])
            op.create_index("ix_rl_request", "request_logs", ["request_id"])

    # ─── security_events ────────────────────────────────────────────
    if not _table_exists("security_events"):
        if _is_postgres():
            op.execute(
                """
                CREATE TABLE security_events (
                  id          BIGSERIAL PRIMARY KEY,
                  ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
                  event_type  VARCHAR(40) NOT NULL,
                  severity    VARCHAR(10) NOT NULL DEFAULT 'info',
                  ip_addr     VARCHAR(64),
                  user_id     INTEGER,
                  path        VARCHAR(512),
                  method      VARCHAR(8),
                  ua          VARCHAR(255),
                  request_id  VARCHAR(36),
                  details     JSONB NOT NULL DEFAULT '{}'::jsonb
                );
                """
            )
            op.execute("CREATE INDEX IF NOT EXISTS ix_se_ts       ON security_events (ts DESC);")
            op.execute("CREATE INDEX IF NOT EXISTS ix_se_type_ts  ON security_events (event_type, ts DESC);")
            op.execute("CREATE INDEX IF NOT EXISTS ix_se_ip_ts    ON security_events (ip_addr, ts DESC);")
            op.execute("CREATE INDEX IF NOT EXISTS ix_se_sev_ts   ON security_events (severity, ts DESC) WHERE severity IN ('warn','critical');")
        else:
            op.create_table(
                "security_events",
                sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                sa.Column("ts", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
                sa.Column("event_type", sa.String(40), nullable=False),
                sa.Column("severity", sa.String(10), nullable=False, server_default="info"),
                sa.Column("ip_addr", sa.String(64), nullable=True),
                sa.Column("user_id", sa.Integer(), nullable=True),
                sa.Column("path", sa.String(512), nullable=True),
                sa.Column("method", sa.String(8), nullable=True),
                sa.Column("ua", sa.String(255), nullable=True),
                sa.Column("request_id", sa.String(36), nullable=True),
                sa.Column("details", sa.Text(), nullable=False, server_default="{}"),
            )
            op.create_index("ix_se_ts", "security_events", ["ts"])
            op.create_index("ix_se_type_ts", "security_events", ["event_type", "ts"])
            op.create_index("ix_se_ip_ts", "security_events", ["ip_addr", "ts"])


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP TABLE IF EXISTS security_events;")
        op.execute("DROP TABLE IF EXISTS request_logs CASCADE;")
    else:
        op.drop_table("security_events")
        op.drop_table("request_logs")
