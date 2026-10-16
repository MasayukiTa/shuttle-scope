"""分母 0 が「測定値」に見える取りこぼし (統計規則 R1/R4) の退行防止テスト。

1. opponent_card: ラリー 0 件の平均ラリー長は 0.0 でなく null
2. partner_comparison: ラリー 0 件のパートナーの平均ラリー長は null (勝率は試合数があるので従来どおり)
3. court_coverage_split: ストローク 0 件の選手の前衛率などは null、balance_score も null
4. yolo の追跡率 / 方向内訳: 分母 0 は null (有効データは従来どおり)

有効データの出力は従来どおりであることも併せて固定する。
"""
from datetime import date

from backend.db.models import Rally, Stroke
from backend.routers.yolo import _share_pct, _tracked_rate
from backend.tests.test_stats_n0_guards_b import (  # noqa: F401
    _headers,
    _match,
    _player,
    client,
)


class TestOpponentCardAvgRally:
    def test_no_rallies_is_null(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        _match(db_session, a, b, date(2026, 1, 1), 0, 0)
        db_session.commit()
        d = client.get(f"/api/analysis/opponent_card?opponent_id={b.id}", headers=_headers()).json()["data"]
        assert d["match_count"] == 1
        assert d["avg_rally_length"] is None

    def test_no_matches_is_null(self, client, db_session):
        b = _player(db_session, "B")
        db_session.commit()
        d = client.get(f"/api/analysis/opponent_card?opponent_id={b.id}", headers=_headers()).json()["data"]
        assert d["match_count"] == 0 and d["avg_rally_length"] is None

    def test_valid_data_unchanged(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        _match(db_session, a, b, date(2026, 1, 1), 2, 3)
        db_session.commit()
        d = client.get(f"/api/analysis/opponent_card?opponent_id={b.id}", headers=_headers()).json()["data"]
        assert d["avg_rally_length"] == 5.0


class TestPartnerComparisonAvgRally:
    def test_partner_without_rallies_has_null_avg_but_real_win_rate(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        pa = _player(db_session, "PA")
        pb = _player(db_session, "PB")
        _match(db_session, a, b, date(2026, 1, 1), 0, 0, fmt="doubles", partner_a=pa, partner_b=pb)
        db_session.commit()
        d = client.get(f"/api/analysis/partner_comparison?player_id={a.id}", headers=_headers()).json()["data"]
        p = d["partners"][0]
        assert p["match_count"] == 1
        assert p["avg_rally_length"] is None
        assert p["win_rate"] == 1.0  # 試合数があるので勝率は実値

    def test_valid_data_unchanged(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        pa = _player(db_session, "PA")
        pb = _player(db_session, "PB")
        _match(db_session, a, b, date(2026, 1, 1), 2, 3, fmt="doubles", partner_a=pa, partner_b=pb)
        db_session.commit()
        d = client.get(f"/api/analysis/partner_comparison?player_id={a.id}", headers=_headers()).json()["data"]
        assert d["partners"][0]["avg_rally_length"] == 5.0


class TestCourtCoverageNoStrokes:
    def _setup(self, db_session, with_strokes_for):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        m = _match(db_session, a, b, date(2026, 1, 1), 1, 2)
        for r in db_session.query(Rally).all():
            for slot in with_strokes_for:
                db_session.add(Stroke(rally_id=r.id, stroke_num=1, player=slot, shot_type="clear", hit_y=0.2))
        db_session.commit()
        return m

    def test_side_without_strokes_is_null_and_balance_null(self, client, db_session):
        m = self._setup(db_session, ["player_a"])
        d = client.get(f"/api/analysis/court_coverage_split?match_id={m.id}", headers=_headers()).json()["data"]
        assert d["player_a"]["total_strokes"] == 2 and d["player_a"]["front_rate"] == 1.0
        assert d["player_b"]["total_strokes"] == 0
        assert d["player_b"]["front_rate"] is None
        assert d["player_b"]["mid_rate"] is None and d["player_b"]["back_rate"] is None
        assert d["balance_score"] is None

    def test_both_sides_with_strokes_unchanged(self, client, db_session):
        m = self._setup(db_session, ["player_a", "player_b"])
        d = client.get(f"/api/analysis/court_coverage_split?match_id={m.id}", headers=_headers()).json()["data"]
        assert d["player_b"]["front_rate"] == 1.0
        assert d["balance_score"] == 1.0


class TestYoloRatios:
    def test_tracked_rate_zero_frames_is_none(self):
        assert _tracked_rate(0, 0) is None

    def test_tracked_rate_valid(self):
        assert _tracked_rate(0, 10) == 1.0
        assert _tracked_rate(5, 10) == 0.5

    def test_share_pct_zero_distance_is_none(self):
        assert _share_pct(0.0, 0.0) is None

    def test_share_pct_valid(self):
        assert _share_pct(1.0, 4.0) == 25.0
        assert _share_pct(0.0, 4.0) == 0.0  # 移動はあるがその方向が 0 は実値の 0%
