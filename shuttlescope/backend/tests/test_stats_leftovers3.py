"""偽の統計の取りこぼし 4 件 (統計ルール R1/R2/R4) の退行防止テスト。

1. compute_win_probability / compute_feature_win_prob: 試合 0 件で 0.5 を返さない
2. win_loss_comparison の ace_rate / error_rate: 未算出は 0.0 でなく null
3. heatmap/composite: 分母 0 のセルの rate は null、各セルに分母 n を併記
4. condition_scoring.calc_deviation: SD=0 の z_score は 0.0 でなく null

有効データの出力は従来どおりであることも併せて固定する。
"""
from datetime import date
from unittest.mock import MagicMock

from backend.analysis.condition_scoring import calc_deviation, factor_label_from_z
from backend.analysis.prediction_engine import (
    compute_feature_win_prob,
    compute_recent_form,
    compute_win_probability,
)
from backend.db.models import Match, Rally, Stroke
from backend.tests.test_stats_n0_guards_b import (  # noqa: F401
    _headers,
    _match,
    _player,
    client,
)


def _pm(result, d):
    m = MagicMock(spec=Match)
    m.player_a_id, m.player_b_id, m.result, m.date = 1, 101, result, d
    m.tournament_level, m.format, m.sets = "IC", "singles", []
    return m


# ── 1. 勝率の事前分布 0.5 ────────────────────────────────────────────────────

class TestWinProbabilityNoPrior:
    def test_no_matches_is_none_with_zero_sample(self):
        assert compute_win_probability([], 1) == (None, 0)

    def test_one_match_is_laplace_smoothed_and_unchanged(self):
        p, n = compute_win_probability([_pm("win", date(2024, 1, 1))], 1)
        assert n == 1 and p == round((1 + 1.0) / (1 + 2.0), 4)

    def test_feature_win_prob_without_matches_is_none_and_flagged(self):
        prob, bd = compute_feature_win_prob([], 1, [], compute_recent_form([], 1), {})
        assert prob is None
        assert bd["insufficient_data"] is True
        assert bd["base_wr"] is None and bd["final"] is None and bd["weights"] == {}

    def test_feature_win_prob_with_data_has_no_flag_key(self):
        ms = [_pm("win", date(2024, 1, i + 1)) for i in range(4)]
        prob, bd = compute_feature_win_prob(ms, 1, [], compute_recent_form(ms, 1, n=0), {})
        assert prob is not None and "insufficient_data" not in bd


class TestPredictionEndpointsNoRecord:
    def test_match_preview_style_predict_without_matches_has_no_fake_probability(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        db_session.commit()
        resp = client.get(
            f"/api/prediction/match_preview?player_id={a.id}&opponent_id={b.id}", headers=_headers()
        )
        assert resp.status_code == 200, resp.text
        d = resp.json()["data"]
        assert d["sample_size"] == 0
        assert d["win_probability"] is None and "win_probability_v2" not in d
        assert d["h2h_win_rate"] is None and d["h2h_n"] == 0
        assert d["set_distribution"] is None and d["match_narrative"] is None
        assert d["insufficient_data"] is True
        assert d["feature_breakdown"]["final"] is None

    def test_match_preview_with_data_keeps_probability(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        for i in range(4):
            _match(db_session, a, b, date(2026, 1, 1 + i), 3, 3)
        db_session.commit()
        d = client.get(
            f"/api/prediction/match_preview?player_id={a.id}&opponent_id={b.id}", headers=_headers()
        ).json()["data"]
        assert d["sample_size"] == 4
        assert d["win_probability"] is not None and d["set_distribution"] is not None
        assert "insufficient_data" not in d

    def test_pair_simulation_without_matches_has_null_distribution(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        db_session.commit()
        d = client.get(
            f"/api/prediction/pair_simulation?player_id_1={a.id}&player_id_2={b.id}", headers=_headers()
        ).json()["data"]
        assert d["win_probability"] is None and d["set_distribution"] is None

    def test_lineup_optimizer_player_without_matches_is_null_last_and_not_recommended(self, client, db_session):
        a = _player(db_session, "HasData")
        b = _player(db_session, "NoData")
        o = _player(db_session, "Opp")
        for i in range(3):
            _match(db_session, a, o, date(2026, 1, 1 + i), 3, 3)
        db_session.commit()
        resp = client.get(f"/api/prediction/lineup_optimizer?player_ids={b.id},{a.id}", headers=_headers())
        assert resp.status_code == 200, resp.text
        d = resp.json()["data"]
        rows = d["ranked_players"]
        assert rows[0]["player_id"] == a.id and rows[0]["win_probability"] is not None
        assert rows[-1]["player_id"] == b.id
        assert rows[-1]["win_probability"] is None and rows[-1]["sample_size"] == 0
        assert d["recommendation"] == "HasData"

    def test_lineup_optimizer_all_without_matches_recommends_nobody(self, client, db_session):
        a = _player(db_session, "N1")
        b = _player(db_session, "N2")
        db_session.commit()
        d = client.get(f"/api/prediction/lineup_optimizer?player_ids={a.id},{b.id}", headers=_headers()).json()["data"]
        assert d["recommendation"] is None
        assert all(r["win_probability"] is None for r in d["ranked_players"])

    def test_analyst_depth_without_matches_flags_breakdown(self, client, db_session):
        a = _player(db_session, "A")
        db_session.commit()
        d = client.get(f"/api/prediction/analyst_depth?player_id={a.id}", headers=_headers()).json()["data"]
        assert d["win_prob_v1"] is None and d["win_prob_v2"] is None
        assert d["feature_breakdown"]["insufficient_data"] is True


# ── 2. ace_rate / error_rate ─────────────────────────────────────────────────

class TestWinLossAceErrorRate:
    def test_ace_and_error_rate_are_null_not_zero(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        _match(db_session, a, b, date(2026, 1, 1), 3, 4, result="win")
        _match(db_session, a, b, date(2026, 1, 2), 1, 4, result="loss")
        db_session.commit()
        resp = client.get(f"/api/analysis/win_loss_comparison?player_id={a.id}", headers=_headers())
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        for side in ("win_matches", "loss_matches"):
            assert data[side]["count"] == 1
            assert data[side]["ace_rate"] is None and data[side]["error_rate"] is None
            # 算出している項目は従来どおり
            assert data[side]["serve_win_rate"] is not None
            assert data[side]["serve_count"] == 4


# ── 3. ヒートマップ合成 ──────────────────────────────────────────────────────

class TestHeatmapCompositeRate:
    def test_no_strokes_cells_have_null_rate_and_n_zero(self, client, db_session):
        a = _player(db_session, "A")
        db_session.commit()
        data = client.get(f"/api/analysis/heatmap/composite?player_id={a.id}", headers=_headers()).json()["data"]
        for part in ("hit", "land_rotated"):
            assert len(data[part]) == 9
            for cell in data[part].values():
                assert cell["count"] == 0 and cell["rate"] is None and cell["n"] == 0

    def test_valid_data_rates_unchanged_with_n(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        m = _match(db_session, a, b, date(2026, 1, 1), 2, 2)
        rallies = db_session.query(Rally).all()
        zones = ["BL", "BL", "NC"]
        # 3 打 (BL x2, NC x1) を player_a の打点・着地点として登録
        for i, z in enumerate(zones):
            db_session.add(Stroke(
                rally_id=rallies[i % len(rallies)].id, stroke_num=i + 1, player="player_a",
                shot_type="smash", hit_zone=z, land_zone=z,
            ))
        db_session.commit()
        data = client.get(f"/api/analysis/heatmap/composite?player_id={a.id}", headers=_headers()).json()["data"]
        hit = data["hit"]
        assert hit["BL"]["count"] == 2 and hit["BL"]["rate"] == round(2 / 3, 4) and hit["BL"]["n"] == 3
        assert hit["NC"]["rate"] == round(1 / 3, 4)
        # n>0 のとき、0 件のセルは 0.0 (実測 0/3) であって null ではない
        assert hit["MC"]["count"] == 0 and hit["MC"]["rate"] == 0.0 and hit["MC"]["n"] == 3
        assert m.id is not None


# ── 4. z_score の番兵 ────────────────────────────────────────────────────────

class TestZScoreSentinel:
    def test_constant_history_gives_null_z_not_zero(self):
        r = calc_deviation(10.0, [10.0] * 8)
        assert r["sd_28"] == 0.0
        assert r["z_score"] is None
        assert factor_label_from_z(r["z_score"]) == "insufficient_data"

    def test_short_history_z_is_null(self):
        assert calc_deviation(10.0, [9.0, 11.0])["z_score"] is None

    def test_valid_history_z_unchanged(self):
        hist = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        r = calc_deviation(10.0, hist)
        mean = 4.0
        sd = (sum((x - mean) ** 2 for x in hist) / 7) ** 0.5
        assert r["z_score"] == float((10.0 - mean) / sd)
