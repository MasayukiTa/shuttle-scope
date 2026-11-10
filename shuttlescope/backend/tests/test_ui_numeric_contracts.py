"""UI点検 B-43 / B-33 / B-26: 分析 API の応答契約 (画面が NaN% / 0% を描かないための値の出どころ)。

- bayes_matchup: 相手名 (opponent_name) を解決して返す
- doubles_role: ダブルス無しでも front/back/neutral_ratio を欠落させない
- rally_length_vs_winrate: 件数 0 の区間の勝率は 0.0 ではなく null
- growth_timeline と growth_judgment: 同一指標のトレンド delta が一致し、
  窓内データ不足の指標があれば総合判定は「改善傾向」にならず pending
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.analysis.growth_engine import (
    compute_metric_growth_trend,
    summarize_growth_population,
)
from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally
from backend.main import app
from backend.tests.test_analysis_endpoints import _admin_auth_ctx
from backend.utils.auth import (
    get_auth,
    require_admin_or_analyst,
    require_non_player,
)


def _player(db, name):
    p = Player(name=name, dominant_hand="R")
    db.add(p)
    db.flush()
    return p


def _match(db, a, b, d, wins_a, n=10, server="player_a", fmt="singles", result="win"):
    m = Match(
        tournament="t", tournament_level="IC", round="r", date=d, format=fmt,
        player_a_id=a.id, player_b_id=b.id, result=result,
        annotation_status="complete", annotation_progress=1.0,
    )
    db.add(m)
    db.flush()
    gs = GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=15)
    db.add(gs)
    db.flush()
    for i in range(1, n + 1):
        db.add(Rally(
            set_id=gs.id, rally_num=i, server=server,
            winner="player_a" if i <= wins_a else "player_b",
            end_type="forced_error", rally_length=5,
            score_a_after=0, score_b_after=0, annotation_mode="manual_record",
        ))
    db.flush()
    return m


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_auth] = _admin_auth_ctx
    app.dependency_overrides[require_admin_or_analyst] = _admin_auth_ctx
    app.dependency_overrides[require_non_player] = _admin_auth_ctx
    yield TestClient(app)
    app.dependency_overrides.clear()


def _twelve_matches(db, serve_server="player_a"):
    a = _player(db, "山田")
    b = _player(db, "標本 桃子")
    ramp = [4, 5, 5, 6, 5, 6, 6, 7, 6, 7, 7, 8]
    for i, w in enumerate(ramp):
        _match(db, a, b, date(2025, 1, 1 + i), w, server=serve_server)
    db.commit()
    return a, b


class TestGrowthSingleSource:
    def test_pure_helper_pending_below_threshold(self):
        pts = [{"value": 0.5, "strength_weight": 0.5} for _ in range(4)]
        out = compute_metric_growth_trend(pts, min_matches=5, trend_delta=0.03, metric="win_rate")
        assert out["trend"] == "pending" and out["trend_delta"] == 0.0

    def test_pure_helper_reports_window_and_periods(self):
        # 12 点 → 窓 4。trend_delta = 最後の 4 点の平均 − 最初の 4 点の平均 (ポイント差)
        pts = [
            {"date": f"2025-01-{i + 1:02d}", "value": 0.4 if i < 4 else 0.6, "strength_weight": 0.5}
            for i in range(12)
        ]
        out = compute_metric_growth_trend(pts, min_matches=5, trend_delta=0.03, metric="win_rate")
        assert out["window"] == 4 and out["n_points"] == 12
        assert out["trend_delta"] == pytest.approx(0.2)
        assert out["early_period"] == {"from": "2025-01-01", "to": "2025-01-04"}
        assert out["recent_period"] == {"from": "2025-01-09", "to": "2025-01-12"}

    def test_pending_helper_has_no_window_or_periods(self):
        pts = [{"date": f"2025-01-0{i + 1}", "value": 0.5, "strength_weight": 0.5} for i in range(4)]
        out = compute_metric_growth_trend(pts, min_matches=5, trend_delta=0.03, metric="win_rate")
        assert out["trend"] == "pending"
        assert out["n_points"] == 4
        assert out["window"] is None
        assert out["early_period"] is None and out["recent_period"] is None

    def test_population_summary_counts_by_reason(self):
        class _M:
            def __init__(self, result):
                self.result = result

        matches = [_M("win"), _M("loss"), _M("loss"), _M("unfinished"), _M("walkover")]
        # win / loss のうち 1 試合はラリーが無く、点にならなかった
        out = summarize_growth_population(matches, used_points=[{}, {}])
        assert out == {"total": 5, "used": 2, "excluded": {"unfinished": 2, "zero_rally": 1}}

    def test_judgment_reports_window_periods_and_population(self, client, db_session):
        a, b = _twelve_matches(db_session)
        _match(db_session, a, b, date(2025, 2, 1), 0, n=0)  # 勝敗確定だがラリー 0
        _match(db_session, a, b, date(2025, 2, 2), 3, n=5, result="unfinished")  # 勝敗未確定
        db_session.commit()
        data = client.get(f"/api/analysis/growth_judgment?player_id={a.id}").json()["data"]
        assert data["population"] == {
            "total": 14, "used": 12, "excluded": {"unfinished": 1, "zero_rally": 1},
        }
        m = data["metrics"]["win_rate"]
        assert m["n_matches"] == 12 and m["window"] == 4
        assert m["early_period"] == {"from": "2025-01-01", "to": "2025-01-04"}
        assert m["recent_period"] == {"from": "2025-01-09", "to": "2025-01-12"}

    def test_timeline_reports_trend_window(self, client, db_session):
        a, _ = _twelve_matches(db_session)
        tl = client.get(f"/api/analysis/growth_timeline?player_id={a.id}&metric=win_rate").json()["data"]
        assert tl["trend_window"] == 4 and tl["trend_n_points"] == 12
        assert tl["trend_early_period"]["from"] == "2025-01-01"
        assert tl["trend_recent_period"]["to"] == "2025-01-12"

    def test_timeline_and_judgment_report_the_same_delta(self, client, db_session):
        a, _ = _twelve_matches(db_session)
        judgment = client.get(f"/api/analysis/growth_judgment?player_id={a.id}").json()["data"]
        jd = judgment["metrics"]["win_rate"]["delta"]
        assert jd != 0.0
        # グラフの平滑化窓が何であっても、表示されるトレンド delta は判定カードと同じ
        for ws in (2, 3, 4):
            tl = client.get(
                f"/api/analysis/growth_timeline?player_id={a.id}&metric=win_rate&window_size={ws}"
            ).json()["data"]
            assert tl["trend_delta"] == jd, ws
            assert tl["trend"] == judgment["metrics"]["win_rate"]["trend"], ws

    def test_overall_verdict_is_pending_when_a_metric_lacks_window_data(self, client, db_session):
        # サーバが常に相手側 → serve_win_rate の点が作れず pending。win_rate だけが改善。
        a, _ = _twelve_matches(db_session, serve_server="player_b")
        data = client.get(f"/api/analysis/growth_judgment?player_id={a.id}").json()["data"]
        assert data["metrics"]["serve_win_rate"]["trend"] == "pending"
        assert data["metrics"]["win_rate"]["trend"] == "improving"
        assert data["judgment"] == "pending"
        assert data["judgment_ja"] == "判定保留"


class TestRallyLengthEmptyBuckets:
    def test_zero_count_bucket_has_null_win_rate(self, client, db_session):
        a, _ = _twelve_matches(db_session)
        data = client.get(f"/api/analysis/rally_length_vs_winrate?player_id={a.id}").json()["data"]
        by_range = {b["range"]: b for b in data["buckets"]}
        assert by_range["4-6"]["count"] > 0 and by_range["4-6"]["win_rate"] is not None
        assert by_range["16+"]["count"] == 0
        assert by_range["16+"]["win_rate"] is None


class TestBayesOpponentNames:
    def test_opponent_name_is_resolved(self, client, db_session):
        a, b = _twelve_matches(db_session)
        resp = client.get(f"/api/analysis/bayes_matchup?player_id={a.id}").json()
        est = resp["data"]["opponent_estimates"]
        assert est and est[0]["opponent_id"] == b.id
        assert est[0]["opponent_name"] == "標本 桃子"
        # 画面が読むキー
        assert "observed_win_rate" in est[0]


class TestDoublesRoleEmptyShape:
    def test_no_doubles_matches_still_returns_every_ratio_key(self, client, db_session):
        a, _ = _twelve_matches(db_session)  # singles のみ
        data = client.get(f"/api/analysis/doubles_role?player_id={a.id}").json()["data"]
        # 打球 0 件の比率は 0.0 ではなく null (統計規則 R1)。キーは欠落させない
        for k in ("front_ratio", "back_ratio", "neutral_ratio"):
            assert k in data and data[k] is None
        assert data["total_shots"] == 0
        assert data["phase_breakdown"] == []
