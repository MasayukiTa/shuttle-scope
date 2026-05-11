"""R43: Canary DB rows + legacy credentials honeypot table.

目的:
  - 攻撃者が DB dump / SQL injection / read replica 侵入で本番 DB を漁ると、
    必ず目に入る場所 (テーブル名・カラム名が「いかにも漏れたら美味しい」もの)
    に honeytoken を 1 行ずつ仕込んでおく。
  - 攻撃者がその値を request に使った瞬間、middleware の honeytoken detector
    (R42 で実装済) が caught する。

仕掛けの中身:
  - 新規 table `_legacy_settings` (key/value のシンプルな KV)
  - 4 rows:
      * LEGACY_VIDEO_STREAM_TOKEN  (= ss_canary_video_token_legacy_*)
      * LEGACY_REFRESH_TOKEN_SEED  (= ss_canary_refresh_v1_*)
      * LEGACY_INTERNAL_WORKER_KEY (= ss_canary_frontend_dbg_*)
      * LEGACY_BACKUP_PASSPHRASE   (= ss_canary_backup_pass_*)

冪等性: IF NOT EXISTS チェック + 値が既にあれば skip。
SQLite / PostgreSQL 両対応。

Revision ID: 0030
Revises: 0029
"""
from alembic import op
import sqlalchemy as sa


revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


_CANARY_ROWS = [
    ("LEGACY_VIDEO_STREAM_TOKEN",
     "ss_canary_video_token_legacy_5fA9c2Bd7eE1fG3hI8jK0l",
     "Legacy video CDN signing token (kept for backward compat)"),
    ("LEGACY_REFRESH_TOKEN_SEED",
     "ss_canary_refresh_v1_b7d4e2a8c6f9013579ace02468135790",
     "Pre-migration refresh token seed (do not rotate yet)"),
    ("LEGACY_INTERNAL_WORKER_KEY",
     "ss_canary_frontend_dbg_W0rK3rPr0duct10nK3y2024XYZ12",
     "Pipeline worker shared secret (legacy fallback)"),
    ("LEGACY_BACKUP_PASSPHRASE",
     "ss_canary_backup_pass_2025_X8nQv3mZpKr7tL9wYeJfHaBc",
     "Backup archive passphrase prior to KMS migration"),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "_legacy_settings" not in inspector.get_table_names():
        op.create_table(
            "_legacy_settings",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("key", sa.String(length=80), nullable=False, unique=True),
            sa.Column("value", sa.Text, nullable=False),
            sa.Column("note", sa.String(length=400), nullable=True),
            sa.Column(
                "created_at", sa.DateTime,
                server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
            ),
        )

    # seed (冪等: key を見て既存ならスキップ)
    conn = bind
    existing = {
        r[0] for r in conn.execute(sa.text("SELECT key FROM _legacy_settings")).fetchall()
    }
    for k, v, note in _CANARY_ROWS:
        if k in existing:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO _legacy_settings (key, value, note) "
                "VALUES (:k, :v, :n)"
            ),
            {"k": k, "v": v, "n": note},
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "_legacy_settings" in inspector.get_table_names():
        op.drop_table("_legacy_settings")
