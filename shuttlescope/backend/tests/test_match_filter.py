"""絞り込み (結果・大会レベル・期間) が解析の母集団に届くことの回帰テスト。

防ぐ事象 (監査 #152): 研究カードの backend が player_id しか受け取らず、画面上部の
絞り込みを変えても N が変わらなかった。MatchFilter (analysis/match_filter.py) を
1 つの依存として受け取り、母集団 (analysis_population + 絞り込み) を全員が同じ関数で決める。

シード (選手 a は常に player_a、相手は b):
  M1: a の勝ち / IC   / 2026-01-10 / 4 ラリー
  M2: a の負け / IC   / 2026-02-10 / 3 ラリー
  M3: a の勝ち / JBC  / 2026-03-10 / 2 ラリー
各ラリーに a の clear と b の smash を 1 本ずつ置く (状態・サンプルが 1 ラリー 1 件になる)。
"""
import re
from datetime import date
from pathlib import Path

import pytest

from backend.analysis.analysis_registry import (
    ANALYSIS_REGISTRY,
    FILTER_SCOPES,
    get_filter_scope,
)
from backend.analysis.match_filter import MatchFilter, select_population
from backend.analysis.optimal_transport_loader import ZONE_LABELS, load_zone_histograms
from backend.db.models import GameSet, Rally, Stroke
from backend.tests.test_stats_n0_guards_b import (  # noqa: F401
    _headers,
    _match,
    _player,
    client,
)

# 絞り込みなし / 結果 / 大会レベル / 期間 ごとの期待値
#   (query, n_matches, n_rallies)
CASES = [
    ("", 3, 9),
    ("&result=win", 2, 6),
    ("&result=loss", 1, 3),
    ("&tournament_level=IC", 2, 7),
    ("&date_from=2026-02-01", 2, 5),
    ("&date_to=2026-02-28", 2, 7),
    ("&result=win&tournament_level=IC", 1, 4),
]


def _seed(db):
    a = _player(db, "A")
    b = _player(db, "B")
    plan = [  # (日付, ラリー数, result, 大会レベル, a の着地ゾーン)
        (date(2026, 1, 10), 4, "win", "IC", "BL"),
        (date(2026, 2, 10), 3, "loss", "IC", "NC"),
        (date(2026, 3, 10), 2, "win", "JBC", "BR"),
    ]
    matches = []
    for d, n, result, level, zone in plan:
        m = _match(db, a, b, d, wins_a=n // 2, n=n, result=result)
        m.tournament_level = level
        db.flush()
        set_ids = [s.id for s in db.query(GameSet).filter(GameSet.match_id == m.id).all()]
        for r in db.query(Rally).filter(Rally.set_id.in_(set_ids)).all():
            db.add(Stroke(rally_id=r.id, stroke_num=1, player="player_a", shot_type="clear",
                          hit_zone="BC", land_zone=zone, hit_y=0.2))
            db.add(Stroke(rally_id=r.id, stroke_num=2, player="player_b", shot_type="smash",
                          hit_zone="BC", land_zone="ML", hit_y=0.2))
        matches.append(m)
    db.commit()
    return a, b, matches


class TestSelectPopulation:
    @pytest.mark.parametrize("query,n_matches,_n_rallies", CASES)
    def test_filter_changes_the_matches(self, db_session, query, n_matches, _n_rallies):
        a, _b, _ms = _seed(db_session)
        mf = _filter_from_query(query)
        matches, _excluded = select_population(db_session, a.id, mf)
        assert len(matches) == n_matches

    def test_no_filter_is_not_applied(self):
        assert MatchFilter().applied is False
        assert MatchFilter(result="win").applied is True
        assert MatchFilter(tournament_level="IC").applied is True

    def test_result_is_from_the_players_side(self, db_session):
        _a, b, ms = _seed(db_session)
        wins_b, _ = select_population(db_session, b.id, MatchFilter(result="win"))
        assert [m.id for m in wins_b] == [ms[1].id]   # M2 は result == loss = b の勝ち


def _filter_from_query(query):
    kw = {}
    for part in [p for p in query.split("&") if p]:
        k, v = part.split("=")
        kw[k] = date.fromisoformat(v) if k.startswith("date_") else v
    return MatchFilter(**kw)


# 母集団 (meta.population) を全員が同じ規則で返すこと
STAMPED = [
    ("exploitability", "/api/analysis/exploitability?player_id={pid}"),
    ("conformal", "/api/analysis/conformal?player_id={pid}"),
    ("policy_eval", "/api/analysis/policy_eval?player_id={pid}"),
    ("style_distance", "/api/analysis/style_distance?player_id={pid}"),
    ("matchup_forecast", "/api/analysis/matchup_forecast?player_id={pid}"),
    ("pair_synergy", "/api/analysis/pair_synergy?player_id={pid}"),
    ("opponent_stats", "/api/analysis/opponent_stats?player_id={pid}"),
    ("growth", "/api/analysis/growth_timeline?player_id={pid}"),
    ("growth", "/api/analysis/growth_judgment?player_id={pid}&min_matches=1"),
]


class TestPopulationInMeta:
    @pytest.mark.parametrize("analysis,url", STAMPED)
    @pytest.mark.parametrize("query,n_matches,n_rallies", CASES)
    def test_population_follows_the_filter(self, client, db_session, analysis, url, query, n_matches, n_rallies):
        a, _b, _ms = _seed(db_session)
        body = client.get(url.format(pid=a.id) + query, headers=_headers()).json()
        meta = body["meta"]
        assert meta["population"] == {
            "n_matches": n_matches,
            "n_rallies": n_rallies,
            "filter_applied": bool(query),
        }
        assert meta["filter_scope"] == "filtered"


class TestFilterReachesTheLoaders:
    """population だけでなく、解析本体の入力 (ローダ) にも絞り込みが届くこと。"""

    def test_exploitability_records(self, client, db_session):
        a, *_ = _seed(db_session)
        for query, _m, n_rallies in CASES:
            body = client.get(f"/api/analysis/exploitability?player_id={a.id}{query}", headers=_headers()).json()
            assert body["meta"]["sample_size"] == n_rallies, query

    def test_conformal_samples(self, client, db_session):
        a, *_ = _seed(db_session)
        for query, _m, n_rallies in CASES:
            body = client.get(f"/api/analysis/conformal?player_id={a.id}{query}", headers=_headers()).json()
            assert body["data"]["n_total"] == n_rallies, query

    def test_policy_eval_records(self, client, db_session):
        a, *_ = _seed(db_session)
        for query, _m, n_rallies in CASES:
            body = client.get(f"/api/analysis/policy_eval?player_id={a.id}{query}", headers=_headers()).json()
            assert body["meta"]["sample_size"] == n_rallies, query

    def test_matchup_forecast_pairs(self, client, db_session):
        a, *_ = _seed(db_session)
        for query, n_matches, _r in CASES:
            body = client.get(f"/api/analysis/matchup_forecast?player_id={a.id}{query}", headers=_headers()).json()
            assert body["meta"]["sample_size"] == n_matches, query

    def test_style_distance_reference_histogram(self, db_session):
        """参照選手の打球だけが絞り込まれる。M2 (負け) の NC は結果=勝ちで消える。"""
        a, _b, _ms = _seed(db_session)
        nc = ZONE_LABELS.index("NC")
        # b は 3 試合に出ているのでコホートに入る (min_matches=3)
        base = load_zone_histograms(db_session, a.id)
        assert base[a.id][nc] == pytest.approx(3 / 9)
        won = load_zone_histograms(db_session, a.id, match_filter=MatchFilter(result="win"))
        assert won[a.id][nc] == 0.0
        assert won[a.id][ZONE_LABELS.index("BL")] == pytest.approx(4 / 6)
        # 参照選手でないコホート選手 b は絞り込みの影響を受けない
        assert won[_b.id].tolist() == pytest.approx(base[_b.id].tolist())

    def test_opponent_stats_rows(self, client, db_session):
        a, *_ = _seed(db_session)
        for query, n_matches, n_rallies in CASES:
            body = client.get(f"/api/analysis/opponent_stats?player_id={a.id}{query}", headers=_headers()).json()
            row = body["data"]["opponents"][0]
            assert row["match_count"] == n_matches, query
            assert row["sample_size"] == n_rallies, query

    def test_growth_points_and_judgment(self, client, db_session):
        a, *_ = _seed(db_session)
        for query, n_matches, _r in CASES:
            tl = client.get(f"/api/analysis/growth_timeline?player_id={a.id}{query}", headers=_headers()).json()
            assert len(tl["data"]["points"]) == n_matches, query
            jd = client.get(f"/api/analysis/growth_judgment?player_id={a.id}&min_matches=1{query}", headers=_headers()).json()
            assert jd["data"]["match_count"] == n_matches, query

    def test_pair_synergy_population(self, client, db_session):
        a, *_ = _seed(db_session)
        for query, n_matches, _r in CASES:
            body = client.get(f"/api/analysis/pair_synergy?player_id={a.id}{query}", headers=_headers()).json()
            assert body["meta"]["sample_size"] == n_matches, query


class TestGlobalOnly:
    def test_rally_sequence_patterns_declares_it_ignores_the_filter(self, client, db_session):
        a, *_ = _seed(db_session)
        body = client.get(
            f"/api/analysis/rally_sequence_patterns?player_id={a.id}&result=win", headers=_headers(),
        ).json()
        assert body["meta"]["filter_scope"] == "global_only"
        assert body["meta"]["population"]["filter_applied"] is False


class TestRegistryDeclaresFilterScope:
    def test_every_entry_declares_a_known_scope(self):
        assert ANALYSIS_REGISTRY
        for name, entry in ANALYSIS_REGISTRY.items():
            assert entry["filter_scope"] in FILTER_SCOPES, name

    def test_unknown_analysis_is_not_wired(self):
        assert get_filter_scope("__not_registered__") == "not_wired"

    def test_every_stamped_endpoint_is_registered_as_filtered(self):
        """@stamps_population("x") を付けた解析は registry で filtered と宣言されている。"""
        routers = Path(__file__).resolve().parents[1] / "routers"
        names = set()
        for path in routers.glob("*.py"):
            names |= set(re.findall(r'@stamps_population\("(\w+)"\)', path.read_text(encoding="utf-8")))
        assert names, "stamps_population を使うエンドポイントが見つからない"
        for name in names:
            assert name in ANALYSIS_REGISTRY, name
            assert ANALYSIS_REGISTRY[name]["filter_scope"] == "filtered", name

    def test_global_only_entries_do_not_take_the_filter(self):
        routers = Path(__file__).resolve().parents[1] / "routers"
        text = "\n".join(p.read_text(encoding="utf-8") for p in routers.glob("*.py"))
        for name, entry in ANALYSIS_REGISTRY.items():
            if entry["filter_scope"] == "global_only":
                assert f'@stamps_population("{name}")' not in text, name
