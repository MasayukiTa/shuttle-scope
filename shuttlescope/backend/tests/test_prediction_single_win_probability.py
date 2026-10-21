"""match_preview / pair_simulation / lineup_optimizer の勝率の出し方 (C1 / C2 / C3)。

1. 画面に出す勝率は win_probability の 1 つだけ。直接対戦だけの Laplace 値は別名 (h2h_win_rate / h2h_n)
2. 最小標本 VERDICT_MIN_SAMPLE 未満は「参考値」として返し、区間は出さない
3. Brier は表示している最終勝率で計算する
"""
from datetime import date, timedelta

from backend.tests.test_stats_n0_guards_b import (  # noqa: F401
    _headers,
    _match,
    _player,
    client,
)
from backend.utils.confidence import VERDICT_MIN_SAMPLE


def _preview(client, a, b):
    resp = client.get(
        f"/api/prediction/match_preview?player_id={a.id}&opponent_id={b.id}", headers=_headers()
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


class TestSingleWinProbability:
    def test_win_probability_is_the_blended_value_and_h2h_has_its_own_name(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        # 直接対戦 4 勝 + 他の相手に 4 敗: 混合後は直接対戦だけの Laplace 値 (5/6) とは別の値になる
        o = _player(db_session, "O")
        for i in range(4):
            _match(db_session, a, b, date(2026, 1, 1) + timedelta(days=i), 3, 3, result="win")
        for i in range(4):
            _match(db_session, a, o, date(2026, 2, 1) + timedelta(days=i), 0, 3, result="loss")
        db_session.commit()
        d = _preview(client, a, b)
        assert "win_probability_v2" not in d
        assert d["h2h_n"] == 4
        assert d["h2h_win_rate"] == round((4 + 1) / (4 + 2), 4)
        assert d["win_probability"] is not None
        assert d["win_probability"] != d["h2h_win_rate"]
        # 画面の数字は feature_breakdown の最終値と同じ
        assert d["win_probability"] == d["feature_breakdown"]["final"]

    def test_without_head_to_head_h2h_fields_are_null_and_zero(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        o = _player(db_session, "O")
        for i in range(3):
            _match(db_session, a, o, date(2026, 1, 1) + timedelta(days=i), 3, 3, result="win")
        db_session.commit()
        d = _preview(client, a, b)
        assert d["h2h_win_rate"] is None and d["h2h_n"] == 0
        assert d["win_probability"] is not None

    def test_below_minimum_is_reference_without_interval_or_direction(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        _match(db_session, a, b, date(2026, 1, 1), 3, 3, result="loss")
        db_session.commit()
        d = _preview(client, a, b)
        ref = d["win_probability_reference"]
        assert ref["is_reference"] is True and ref["reason"] == "sample"
        assert ref["min_sample"] == VERDICT_MIN_SAMPLE and ref["sample_size"] == 1
        assert d["win_probability_ci"] is None
        assert d["recent_form"]["trend"] is None
        assert d["caution_flags"] == []
        assert d["brier_score"]["score"] is None

    def test_at_minimum_is_not_reference_and_has_wilson_interval(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        for i in range(VERDICT_MIN_SAMPLE):
            res = "win" if i % 2 == 0 else "loss"
            _match(db_session, a, b, date(2026, 1, 1) + timedelta(days=i), 3, 3, result=res)
        db_session.commit()
        d = _preview(client, a, b)
        ci = d["win_probability_ci"]
        assert ci is not None and ci["n"] == VERDICT_MIN_SAMPLE
        assert ci["low"] < d["win_probability"] < ci["high"]
        assert d["brier_score"]["score"] is not None
        # 理由が sample でないこと (Brier が poor なら brier で参考値になりうる)
        assert d["win_probability_reference"]["reason"] in (None, "brier")

    def test_pair_simulation_below_minimum_is_reference(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        resp = client.get(
            f"/api/prediction/pair_simulation?player_id_1={a.id}&player_id_2={b.id}", headers=_headers()
        )
        assert resp.status_code == 200, resp.text
        d = resp.json()["data"]
        assert d["win_probability_reference"]["is_reference"] is True
        assert d["win_probability_ci"] is None

    def test_lineup_rows_carry_wilson_interval_only_at_minimum(self, client, db_session):
        a = _player(db_session, "Many")
        c = _player(db_session, "Few")
        o = _player(db_session, "Opp")
        for i in range(VERDICT_MIN_SAMPLE):
            _match(db_session, a, o, date(2026, 1, 1) + timedelta(days=i), 3, 3, result="win")
        _match(db_session, c, o, date(2026, 1, 1), 3, 3, result="win")
        db_session.commit()
        resp = client.get(
            f"/api/prediction/lineup_optimizer?player_ids={a.id},{c.id}&opponent_id={o.id}",
            headers=_headers(),
        )
        assert resp.status_code == 200, resp.text
        rows = {r["player_id"]: r for r in resp.json()["data"]["ranked_players"]}
        assert rows[a.id]["win_probability_ci"] is not None
        assert rows[a.id]["win_probability_reference"]["is_reference"] is False
        assert rows[c.id]["win_probability_ci"] is None
        assert rows[c.id]["win_probability_reference"]["is_reference"] is True
        assert rows[c.id]["recent_trend"] is None


class TestSufficiencyScoreCanCut:
    def test_score_is_below_half_under_minimum_and_monotone(self):
        from backend.routers.live_coach import _sufficiency_score
        below = [_sufficiency_score(n, cap=0.95) for n in range(0, VERDICT_MIN_SAMPLE)]
        assert all(s < 0.5 for s in below)
        assert _sufficiency_score(VERDICT_MIN_SAMPLE, cap=0.95) == 0.5
        series = [_sufficiency_score(n, cap=0.95) for n in range(0, 40)]
        assert series == sorted(series)
        assert series[-1] == 0.95
