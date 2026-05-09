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
    """Round 258 R13 P0 fix (regression of R12): SQLite は ALTER COLUMN NOT NULL を
    サポートしないため、`alter_column` 系は `with op.batch_alter_table` で囲む。
    PostgreSQL では batch_alter_table は通常の ALTER に展開され、SQLite では
    table 再作成方式で動く。本 repo の他 migration (0013 等) と同じ pattern。

    流れ:
      1. add_column (nullable=True で安全に追加)
      2. UPDATE で既存行に default 値を埋める
      3. batch_alter_table で nullable=False に昇格 + UNIQUE 等を追加

    冪等性: `_existing_columns` で先に存在確認するので multiple run でも no-op。
    """
    bind = op.get_bind()
    cols = _existing_columns(bind, "analysis_cache")
    if not cols:
        # テーブルが存在しない (新規 deploy) → create_all() に任せる。本 migration は no-op。
        return

    # ─── Phase 1a: 不足列を nullable=True で追加 ───
    # Round 258 R17 P2 fix (NEW-5): R12 までは UPDATE backfill を
    # `if "X" not in cols:` ブロック内に書いていた。問題は、前回実行で add_column は
    # 成功したが Phase 2 の NOT NULL 昇格で例外死した場合、再実行時には
    # 「カラムは既に存在 → backfill UPDATE が走らない → 一部行が IS NULL のまま
    # → Phase 2 が再度 IntegrityError」という詰みパターンに陥る。
    # 修正: add_column と UPDATE backfill を分離し、UPDATE は **無条件で**
    # 実行する。`WHERE X IS NULL` で副作用は完全に冪等。
    if "cache_key" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("cache_key", sa.String(length=200), nullable=True),
        )
    if "analysis_type" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("analysis_type", sa.String(length=50), nullable=True),
        )
    if "filters_json" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("filters_json", sa.Text(), nullable=True),
        )
    if "result_json" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("result_json", sa.Text(), nullable=True),
        )
    if "sample_size" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("sample_size", sa.Integer(), nullable=True, server_default="0"),
        )
    if "confidence_level" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("confidence_level", sa.Float(), nullable=True, server_default="0.0"),
        )
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
    if "player_id" not in cols:
        op.add_column(
            "analysis_cache",
            sa.Column("player_id", sa.Integer(), nullable=True, server_default="-1"),
        )

    # ─── Phase 1b: 既存 NULL 行を default で埋める (idempotent backfill) ───
    # WHERE ... IS NULL で何度実行しても同じ結果。前回の Phase 2 失敗からの
    # 復旧再実行でも確実に NOT NULL 制約を満たせる状態にする。
    op.execute(
        "UPDATE analysis_cache SET cache_key = 'legacy_' || CAST(id AS VARCHAR) "
        "WHERE cache_key IS NULL"
    )
    op.execute("UPDATE analysis_cache SET analysis_type = 'unknown' WHERE analysis_type IS NULL")
    op.execute("UPDATE analysis_cache SET filters_json = '{}' WHERE filters_json IS NULL")
    op.execute("UPDATE analysis_cache SET result_json = '{}' WHERE result_json IS NULL")
    op.execute("UPDATE analysis_cache SET sample_size = 0 WHERE sample_size IS NULL")
    op.execute("UPDATE analysis_cache SET confidence_level = 0.0 WHERE confidence_level IS NULL")
    op.execute("UPDATE analysis_cache SET expires_at = CURRENT_TIMESTAMP WHERE expires_at IS NULL")
    op.execute("UPDATE analysis_cache SET player_id = -1 WHERE player_id IS NULL")

    # ─── Phase 2: NOT NULL 昇格 + UNIQUE は batch_alter_table で SQLite 互換 ───
    # 直前で全行を埋めたので、ここでの NOT NULL 化は安全。
    with op.batch_alter_table("analysis_cache", recreate="auto") as batch:
        # 各 column は phase 1 の add_column 後 or 既存。NOT NULL 化を冪等に。
        batch.alter_column("cache_key", existing_type=sa.String(length=200), nullable=False)
        batch.alter_column("analysis_type", existing_type=sa.String(length=50), nullable=False)
        batch.alter_column("filters_json", existing_type=sa.Text(), nullable=False)
        batch.alter_column("result_json", existing_type=sa.Text(), nullable=False)
        batch.alter_column("expires_at", existing_type=sa.DateTime(), nullable=False)
        batch.alter_column("player_id", existing_type=sa.Integer(), nullable=False)

    # UNIQUE は batch 外で (既存 unique がある場合は IntegrityError を握り潰す)
    try:
        op.create_unique_constraint(
            "uq_analysis_cache_cache_key", "analysis_cache", ["cache_key"]
        )
    except Exception:
        pass


def downgrade() -> None:
    # 本 migration は不足列の追加のみ。downgrade は no-op (削除すると idempotency
    # ロジックが壊れるため、ロールバック時はテーブル単位で手動対応)。
    pass
