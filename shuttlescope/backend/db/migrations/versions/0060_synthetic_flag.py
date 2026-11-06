"""matches.is_synthetic - explicit marker that a match is synthetic/validation data (g32 / audit #178)

Why this column exists
----------------------
Audit item #178: of the 53 matches in the full export, 28 are BIAS_SEED fixtures
(2,721 / 4,449 rallies = 61.2%). They are intentional validation fixtures, but the
match object carried no synthetic/test/fixture attribute, so they flowed into the
same growth / opponent / tournament / research analyses as real matches. We add a
persisted boolean `is_synthetic` so synthetic data can never be mistaken for real
data and is excluded from every population/aggregate analysis by default through
one shared helper (analysis.analysis_population.split_analysis_population, which
excludes is_synthetic rows unless include_synthetic=True is passed by an admin tool).

fail closed: NOT NULL with server default False. Every pre-existing row is treated
as real (False); synthetic=True is set only by an explicit backfill of validation
fixtures and by future ingestion of seed rows.

Backfill: the backend has no code path that *creates* the BIAS_SEED rows (they are
ingested from outside under a tournament-name convention; see
src/utils/exportCandidates.ts INTERNAL_TOURNAMENT). So we tag existing rows whose
`tournament` matches that same convention (BIAS_SEED / DEMO / TEST / デモ / テスト)
as synthetic. Rows that do not match are left False (fail closed).

Additive only: one NOT NULL column with a server default; no data loss.

Revision ID: 0060
Revises: 0059
"""
from alembic import op
import sqlalchemy as sa

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None

_TABLE = "matches"
_COLUMN = "is_synthetic"
_INDEX = "ix_matches_is_synthetic"

# tournament 名規約 (src/utils/exportCandidates.ts INTERNAL_TOURNAMENT と同じ集合)。
# 先頭が BIAS_SEED / DEMO / TEST (区切り文字か終端) または デモ / テスト。
_SEED_LIKE = (
    "BIAS_SEED%",
    "DEMO %", "DEMO_%", "DEMO-%", "DEMO:%", "DEMO：%", "DEMO",
    "TEST %", "TEST_%", "TEST-%", "TEST:%", "TEST：%", "TEST",
    "デモ%", "テスト%",
)


def upgrade() -> None:
    # bootstrap で Base.metadata.create_all が models からこの列を先に作ることが
    # あるため、alembic でも二重作成にならないよう存在チェックしてから add_column する
    # (0056 / 0057 / 0058 / 0059 と同じ idempotent パターン)。
    insp = sa.inspect(op.get_bind())
    existing = {c["name"] for c in insp.get_columns(_TABLE)}
    if _COLUMN not in existing:
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # 既存行 (create_all 経路で NULL が残り得る) を明示的に False へ寄せる。
    op.execute(
        sa.text(f"UPDATE {_TABLE} SET {_COLUMN} = false WHERE {_COLUMN} IS NULL")
    )

    # 検証用 fixture を backfill: tournament 名が規約に合致する行だけ True。
    # PostgreSQL の LIKE は大文字小文字を区別するため UPPER で正規化してから比較する
    # (exportCandidates.ts の /i と揃える)。パターンも大文字で持つ。デモ/テストは
    # UPPER で不変なのでそのまま一致する。
    for pat in _SEED_LIKE:
        op.execute(
            sa.text(
                f"UPDATE {_TABLE} SET {_COLUMN} = true "
                f"WHERE {_COLUMN} = false AND UPPER(tournament) LIKE :p"
            ).bindparams(p=pat.upper())
        )

    existing_indexes = {i["name"] for i in insp.get_indexes(_TABLE)}
    if _INDEX not in existing_indexes:
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _INDEX in {i["name"] for i in insp.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in {c["name"] for c in insp.get_columns(_TABLE)}:
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_column(_COLUMN)
        else:
            op.drop_column(_TABLE, _COLUMN)
