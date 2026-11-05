"""audit #178: matches.is_synthetic (検証用 fixture マーカー) の回帰テスト。

BIAS_SEED 等の合成データが通常の成長・対戦相手・大会・研究分析に混入していた。
`matches.is_synthetic` を永続マーカーとして追加し、単一の共有ヘルパ
(analysis.analysis_population.split_analysis_population) が既定で除外することを固定する。
fail closed: is_synthetic が True の試合だけを外し、False / NULL / 属性なしは実データ扱い。
管理ツールは include_synthetic=True で取り込める。
"""
import importlib.util
from datetime import date
from pathlib import Path

from alembic.script import ScriptDirectory

from backend.analysis.analysis_population import (
    is_synthetic_match,
    split_analysis_population,
)
from backend.analysis.router_helpers import _get_player_matches_with_excluded
from backend.tests.test_stats_n0_guards_b import (  # noqa: F401
    _headers,
    _match,
    _player,
    client,
)

_VERSIONS = Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions"


# ── migration 0060 の識別子と single head ──────────────────────────────

def _load_migration():
    # 数字始まりのファイル名は通常 import できないため importlib で直接ロードする
    # (test_land_zone_source.py の _load_migration と同じ方式)。
    path = next(_VERSIONS.glob("0060_*.py"))
    spec = importlib.util.spec_from_file_location("mig_0060_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_0060_revision_identifiers():
    mod = _load_migration()
    assert mod.revision == "0060" and mod.down_revision == "0059"


def test_migration_0060_is_the_single_head():
    scripts = ScriptDirectory(str(_VERSIONS.parent))
    heads = scripts.get_heads()
    # 後続の移行が増えても成り立つよう、最新が 1 つで 0060 がその履歴に含まれることを確かめる
    assert len(heads) == 1
    chain = {rev.revision for rev in scripts.iterate_revisions(heads[0], "base")}
    assert "0060" in chain and "0059" in chain


def test_migration_0060_adds_column_and_backfills(tmp_path):
    import sqlalchemy as sa
    from alembic.runtime.migration import MigrationContext
    from alembic.operations import Operations
    mod = _load_migration()

    engine = sa.create_engine("sqlite://")  # in-memory, never a real app DB
    with engine.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE matches (id INTEGER PRIMARY KEY, tournament VARCHAR(80))"))
        conn.execute(sa.text(
            "INSERT INTO matches (id, tournament) VALUES "
            "(1, 'BIAS_SEED_20260415_SINGLES_1'), (2, '全日本総合'), "
            "(3, 'DEMO 大会'), (4, 'デモ'), (5, 'TEST-CUP'), (6, 'Japan Open')"))

    def _run(fn):
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                fn()

    _run(mod.upgrade)
    with engine.begin() as conn:
        cols = {c["name"] for c in sa.inspect(engine).get_columns("matches")}
        assert "is_synthetic" in cols
        rows = conn.execute(sa.text(
            "SELECT id, is_synthetic FROM matches ORDER BY id")).all()
    got = {int(i): int(v) for i, v in rows}
    # BIAS_SEED / DEMO / デモ / TEST は synthetic=1、実データは 0 (fail closed)
    assert got == {1: 1, 2: 0, 3: 1, 4: 1, 5: 1, 6: 0}

    _run(mod.upgrade)  # idempotent
    assert [c["name"] for c in sa.inspect(engine).get_columns("matches")].count(
        "is_synthetic") == 1

    _run(mod.downgrade)
    assert "is_synthetic" not in {
        c["name"] for c in sa.inspect(engine).get_columns("matches")}


# ── is_synthetic_match ヘルパ (fail closed) ────────────────────────────

class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_is_synthetic_match_fail_closed():
    assert is_synthetic_match(_Obj(is_synthetic=True)) is True
    assert is_synthetic_match(_Obj(is_synthetic=False)) is False
    assert is_synthetic_match(_Obj(is_synthetic=None)) is False
    assert is_synthetic_match(_Obj()) is False  # 旧データ (属性なし) = 実データ扱い


# ── split_analysis_population が synthetic を既定で除外 ────────────────────

def _two_real_one_synthetic(db):
    a = _player(db, "A")
    b = _player(db, "B")
    m_real = _match(db, a, b, date(2026, 1, 1), 5, 10, result="win")
    m_real2 = _match(db, a, b, date(2026, 1, 2), 5, 10, result="loss")
    m_syn = _match(db, a, b, date(2026, 1, 3), 5, 10, result="win")
    m_syn.is_synthetic = True
    db.commit()
    return a, b, m_real, m_real2, m_syn


class TestPopulationExcludesSynthetic:
    def test_split_excludes_synthetic_by_default(self, db_session):
        a, _b, m_real, m_real2, m_syn = _two_real_one_synthetic(db_session)
        included, excluded = split_analysis_population(
            db_session, [m_real, m_real2, m_syn])
        assert [m.id for m in included] == [m_real.id, m_real2.id]
        # synthetic は unfinished / zero_rally には数えない (excluded dict の形は変えない)
        assert excluded == {"unfinished": 0, "zero_rally": 0}

    def test_include_synthetic_opts_in(self, db_session):
        a, _b, m_real, m_real2, m_syn = _two_real_one_synthetic(db_session)
        included, _excluded = split_analysis_population(
            db_session, [m_real, m_real2, m_syn], include_synthetic=True)
        assert [m.id for m in included] == [m_real.id, m_real2.id, m_syn.id]

    def test_get_player_matches_excludes_synthetic(self, db_session):
        a, _b, m_real, m_real2, _m_syn = _two_real_one_synthetic(db_session)
        matches, _excluded = _get_player_matches_with_excluded(db_session, a.id)
        assert sorted(m.id for m in matches) == sorted([m_real.id, m_real2.id])

    def test_get_player_matches_include_synthetic(self, db_session):
        a, _b, m_real, m_real2, m_syn = _two_real_one_synthetic(db_session)
        matches, _excluded = _get_player_matches_with_excluded(
            db_session, a.id, include_synthetic=True)
        assert sorted(m.id for m in matches) == sorted(
            [m_real.id, m_real2.id, m_syn.id])


class TestEndpointExcludesSynthetic:
    def test_opponent_stats_drops_synthetic(self, client, db_session):
        a, b, m_real, m_real2, _m_syn = _two_real_one_synthetic(db_session)
        body = client.get(
            f"/api/analysis/opponent_stats?player_id={a.id}",
            headers=_headers()).json()
        row = body["data"]["opponents"][0]
        assert row["opponent_id"] == b.id
        # 実データ 2 試合のみ (synthetic 1 試合は母集団から外れる)
        assert row["match_count"] == 2
        assert row["win_rate"] == 0.5
