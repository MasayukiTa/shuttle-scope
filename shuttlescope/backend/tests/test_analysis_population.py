"""解析母集団の定義 (analysis_population) の回帰テスト。

勝敗が確定した試合 (win / loss) で、かつ有効なラリーが 1 本以上ある試合だけを
勝率の分母に入れる。未完了 (unfinished) の試合を「負け」に数えない。
除外した試合は理由別の件数 (unfinished / zero_rally) を meta.excluded で返す。

対象: analysis_population / router_helpers / opponent_stats /
      tournament_level_comparison / pair_synergy / growth_engine。
"""
from datetime import date

from backend.analysis.analysis_population import (
    exclusion_reason,
    is_decided_result,
    split_analysis_population,
)
from backend.analysis.growth_engine import growth_points_weighted
from backend.analysis.router_helpers import _get_player_matches_with_excluded
from backend.tests.test_stats_n0_guards_b import (  # noqa: F401
    _headers,
    _match,
    _player,
    client,
)


def _mixed_singles(db):
    """選手 a の試合: 勝ち 1 / 負け 1 / 未完了 1 / ラリー 0 本の勝ち 1。相手は全て b。"""
    a = _player(db, "A")
    b = _player(db, "B")
    m_win = _match(db, a, b, date(2026, 1, 1), 5, 10, result="win")
    m_loss = _match(db, a, b, date(2026, 1, 2), 5, 10, result="loss")
    m_unfinished = _match(db, a, b, date(2026, 1, 3), 2, 4, result="unfinished")
    m_zero = _match(db, a, b, date(2026, 1, 4), 0, 0, result="win")
    db.commit()
    return a, b, m_win, m_loss, m_unfinished, m_zero


EXPECTED_EXCLUDED = {"unfinished": 1, "zero_rally": 1}


class TestPopulationDefinition:
    def test_decided_results_are_win_and_loss_only(self):
        assert is_decided_result("win") and is_decided_result("loss")
        for r in ("unfinished", "walkover", None, ""):
            assert not is_decided_result(r)

    def test_exclusion_reason(self):
        assert exclusion_reason("win", 3) is None
        assert exclusion_reason("loss", 1) is None
        assert exclusion_reason("unfinished", 8) == "unfinished"
        assert exclusion_reason("walkover", 0) == "unfinished"  # 重なるときは未完了に数える
        assert exclusion_reason("win", 0) == "zero_rally"

    def test_split_counts_each_match_once(self, db_session):
        a, _b, m_win, m_loss, _m_unf, _m_zero = _mixed_singles(db_session)
        all_matches = [m_win, m_loss, _m_unf, _m_zero]
        included, excluded = split_analysis_population(db_session, all_matches)
        assert [m.id for m in included] == [m_win.id, m_loss.id]
        assert excluded == EXPECTED_EXCLUDED

    def test_split_empty(self, db_session):
        assert split_analysis_population(db_session, []) == ([], {"unfinished": 0, "zero_rally": 0})

    def test_get_player_matches_uses_the_same_population(self, db_session):
        a, _b, m_win, m_loss, *_ = _mixed_singles(db_session)
        matches, excluded = _get_player_matches_with_excluded(db_session, a.id)
        assert sorted(m.id for m in matches) == sorted([m_win.id, m_loss.id])
        assert excluded == EXPECTED_EXCLUDED


class TestEndpointsUseThePopulation:
    def test_opponent_stats(self, client, db_session):
        a, b, *_ = _mixed_singles(db_session)
        body = client.get(f"/api/analysis/opponent_stats?player_id={a.id}", headers=_headers()).json()
        row = body["data"]["opponents"][0]
        assert row["opponent_id"] == b.id
        assert row["match_count"] == 2          # 勝ち 1 + 負け 1。未完了と 0 ラリーは入らない
        assert row["win_rate"] == 0.5           # 1 / 2
        assert row["sample_size"] == 20         # 10 + 10 ラリー
        assert body["meta"]["excluded"] == EXPECTED_EXCLUDED

    def test_opponent_stats_only_unfinished_is_empty_not_zero(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        _match(db_session, a, b, date(2026, 1, 1), 2, 4, result="unfinished")
        db_session.commit()
        body = client.get(f"/api/analysis/opponent_stats?player_id={a.id}", headers=_headers()).json()
        assert body["data"]["opponents"] == []
        assert body["meta"]["sample_size"] == 0
        assert body["meta"]["excluded"] == {"unfinished": 1, "zero_rally": 0}

    def test_opponent_stats_from_the_b_side(self, client, db_session):
        a, b, *_ = _mixed_singles(db_session)
        body = client.get(f"/api/analysis/opponent_stats?player_id={b.id}", headers=_headers()).json()
        row = body["data"]["opponents"][0]
        assert row["opponent_id"] == a.id
        assert row["match_count"] == 2 and row["win_rate"] == 0.5
        assert body["meta"]["excluded"] == EXPECTED_EXCLUDED

    def test_tournament_level_comparison(self, client, db_session):
        a, *_ = _mixed_singles(db_session)
        body = client.get(
            f"/api/analysis/tournament_level_comparison?player_id={a.id}", headers=_headers(),
        ).json()
        levels = body["data"]["levels"]
        assert len(levels) == 1
        assert levels[0]["match_count"] == 2
        assert levels[0]["win_rate"] == 0.5
        assert levels[0]["sample_size"] == 20
        assert body["meta"]["sample_size"] == 2
        assert body["meta"]["excluded"] == EXPECTED_EXCLUDED

    def test_pair_synergy(self, client, db_session):
        a = _player(db_session, "A")
        p = _player(db_session, "P")
        o1 = _player(db_session, "O1")
        o2 = _player(db_session, "O2")
        kw = dict(fmt="womens_doubles", partner_a=p, partner_b=o2)
        _match(db_session, a, o1, date(2026, 1, 1), 5, 5, result="win", **kw)
        _match(db_session, a, o1, date(2026, 1, 2), 5, 5, result="loss", **kw)
        _match(db_session, a, o1, date(2026, 1, 3), 2, 3, result="unfinished", **kw)
        _match(db_session, a, o1, date(2026, 1, 4), 0, 0, result="win", **kw)
        db_session.commit()
        body = client.get(f"/api/analysis/pair_synergy?player_id={a.id}", headers=_headers()).json()
        assert body["data"]["player_avg_win_rate"] == 0.5     # 1 / 2
        pair = body["data"]["pairs"][0]
        assert pair["partner_id"] == p.id
        assert pair["match_count"] == 2 and pair["win_rate"] == 0.5
        assert body["meta"]["sample_size"] == 2
        assert body["meta"]["excluded"] == EXPECTED_EXCLUDED

    def test_pair_synergy_partner_on_b_side_wins_with_loss_result(self, client, db_session):
        """result は player_a 側基準。player_b 側の相方は result == loss で勝ち。"""
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        pa = _player(db_session, "PA")
        pb = _player(db_session, "PB")
        _match(db_session, a, b, date(2026, 1, 1), 5, 5, result="loss",
               fmt="womens_doubles", partner_a=pa, partner_b=pb)
        db_session.commit()
        body = client.get(f"/api/analysis/pair_synergy?player_id={pb.id}", headers=_headers()).json()
        assert body["data"]["player_avg_win_rate"] == 1.0
        assert body["data"]["pairs"][0]["win_rate"] == 1.0


class TestGrowthSkipsUndecided:
    def test_unfinished_match_is_not_a_growth_point(self, db_session):
        a, _b, m_win, m_loss, m_unf, m_zero = _mixed_singles(db_session)
        pts = growth_points_weighted([m_win, m_loss, m_unf, m_zero], a.id, db_session, metric="win_rate")
        assert [p["match_id"] for p in pts] == [m_win.id, m_loss.id]
        assert all(p["rally_count"] == 10 for p in pts)
