"""Ensure analysis_cache has idempotency-compatible columns.

Round 258 R10/R11/R12 で idempotency 永続化を AnalysisCache テーブルに乗せる
設計に変更したが、`AnalysisCache` モデルが定義する以下の列が古い prod DB に
存在しない可能性が指摘された (R12 REG-3):
  - cache_key (UNIQUE)
  - filters_json (NOT NULL)
  - result_json (NOT NULL)
  - sample_size (default 0)
  - confidence_level (default 0.0)
  - computed_at (default now)

`Base.metadata.create_all()` は CREATE TABLE IF NOT EXISTS のみで、既存
テーブルへの ALTER は行わない。本 migration で不足列を補い、既存行は
ダミー値 (空 JSON / 0 / now) で埋めて NOT NULL 制約を満たす。

冪等性: `inspector.get_columns` で既存列を列挙し、不足分のみ追加。
複数回実行しても二重追加にはならない。

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def _existing_columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _existing_columns(bind, "analysis_cache")
    if not cols:
        # テーブルが存在しない (新規 deploy) → create_all() に任せる。本 migration は no-op。
        return

    # 必要な列を順次追加 (NOT NULL は default 値で安全に追加)
    if "cache_key" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("cache_key", sa.String(length=200), nullable=True),
        )
        # 既存行の cache_key を埋める (id ベースのダミー)
        op.execute("UPDATE analysis_cache SET cache_key = 'legacy_' || CAST(id AS VARCHAR) WHERE cache_key IS NULL")
        op.alter_column("analysis_cache", "cache_key", nullable=False)
        # UNIQUE 制約
        try:
            op.create_unique_constraint("uq_analysis_cache_cache_key", "analysis_cache", ["cache_key"])
        except Exception:
            # 既存 unique がある場合のスキップ
            pass

    if "analysis_type" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("analysis_type", sa.String(length=50), nullable=True),
        )
        op.execute("UPDATE analysis_cache SET analysis_type = 'unknown' WHERE analysis_type IS NULL")
        op.alter_column("analysis_cache", "analysis_type", nullable=False)

    if "filters_json" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("filters_json", sa.Text(), nullable=True),
        )
        op.execute("UPDATE analysis_cache SET filters_json = '{}' WHERE filters_json IS NULL")
        op.alter_column("analysis_cache", "filters_json", nullable=False)

    if "result_json" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("result_json", sa.Text(), nullable=True),
        )
        op.execute("UPDATE analysis_cache SET result_json = '{}' WHERE result_json IS NULL")
        op.alter_column("analysis_cache", "result_json", nullable=False)

    if "sample_size" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("sample_size", sa.Integer(), nullable=True, server_default="0"),
        )
        op.execute("UPDATE analysis_cache SET sample_size = 0 WHERE sample_size IS NULL")

    if "confidence_level" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("confidence_level", sa.Float(), nullable=True, server_default="0.0"),
        )
        op.execute("UPDATE analysis_cache SET confidence_level = 0.0 WHERE confidence_level IS NULL")

    if "computed_at" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("computed_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    if "expires_at" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("expires_at", sa.DateTime(), nullable=True),
        )
        op.execute("UPDATE analysis_cache SET expires_at = CURRENT_TIMESTAMP WHERE expires_at IS NULL")
        op.alter_column("analysis_cache", "expires_at", nullable=False)

    # player_id NOT NULL — idempotency 用 sentinel 0 / 既存行は -1 で埋める
    if "player_id" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("player_id", sa.Integer(), nullable=True, server_default="-1"),
        )
        op.execute("UPDATE analysis_cache SET player_id = -1 WHERE player_id IS NULL")
        op.alter_column("analysis_cache", "player_id", nullable=False)


def downgrade() -> None:
    # 本 migration は不足列の追加のみ。downgrade は no-op (削除すると idempotency
    # ロジックが壊れるため、ロールバック時はテーブル単位で手動対応)。
    pass
