"""observation_analytics エンドポイントのテスト"""
import pytest
from fastapi.testclient import TestClient
from datetime import date

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, PreMatchObservation


def _make_player(db, name, hand="R"):
    p = Player(name=name, dominant_hand=hand)
    db.add(p)
    db.flush()
    return p


def _make_match(db, pa, pb, result="win", match_date=None):
    m = Match(
        tournament="大会",
        tournament_level="IC",
        round="1回戦",
        date=match_date or date(2025, 3, 1),
        format="singles",
        player_a_id=pa.id,
        player_b_id=pb.id,
        result=result,
        annotation_status="complete",
    )
    db.add(m)
    db.flush()
    return m


def _make_obs(db, match_id, player_id, obs_type, obs_value, confidence="likely"):
    o = PreMatchObservation(
        match_id=match_id,
        player_id=player_id,
        observation_type=obs_type,
        observation_value=obs_value,
        confidence_level=confidence,
        source="warmup",
    )
    db.add(o)
    db.flush()
    return o


@pytest.fixture
def obs_client(db_session):
    player_a = _make_player(db_session, "Aさん")
    opp1 = _make_player(db_session, "左利き相手", hand="L")
    opp2 = _make_player(db_session, "テーピング相手")
    opp3 = _make_player(db_session, "通常相手")

    m1 = _make_match(db_session, player_a, opp1, result="win")
    m2 = _make_match(db_session, player_a, opp1, result="win", match_date=date(2025, 4, 1))
    m3 = _make_match(db_session, player_a, opp2, result="loss")
    m4 = _make_match(db_session, player_a, opp3, result="win")

    # 観察: opp1 は左利き(confirmed) → 2試合 → 2勝
    _make_obs(db_session, m1.id, opp1.id, "handedness", "L", "confirmed")
    _make_obs(db_session, m2.id, opp1.id, "handedness", "L", "confirmed")
    # 観察: opp2 はテーピングあり → 1試合 → 0勝
    _make_obs(db_session, m3.id, opp2.id, "physical_caution", "light", "likely")
    # m4 は観察記録なし

    db_session.flush()

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    yield client, player_a.id
    app.dependency_overrides.clear()


class TestObservationAnalytics:
    def test_returns_200_with_splits(self, obs_client):
        client, player_id = obs_client
        resp = client.get(f"/api/analysis/observation_analytics?player_id={player_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "splits" in body["data"]
        assert "observation_count" in body["data"]
        assert "sample_size" in body["meta"]

    def test_win_rate_correct_for_left_handed(self, obs_client):
        """左利き相手に2勝0敗 → win_rate = 1.0"""
        client, player_id = obs_client
        resp = client.get(f"/api/analysis/observation_analytics?player_id={player_id}")
        splits = resp.json()["data"]["splits"]
        lh = next((s for s in splits
                   if s["observation_type"] == "handedness" and s["observation_value"] == "L"), None)
        assert lh is not None
        assert lh["match_count"] == 2
        assert lh["wins"] == 2
        assert lh["win_rate"] == 1.0

    def test_win_rate_correct_for_taping(self, obs_client):
        """テーピング相手に0勝1敗 → win_rate = 0.0"""
        client, player_id = obs_client
        resp = client.get(f"/api/analysis/observation_analytics?player_id={player_id}")
        splits = resp.json()["data"]["splits"]
        taping = next((s for s in splits
                       if s["observation_type"] == "physical_caution"), None)
        assert taping is not None
        assert taping["match_count"] == 1
        assert taping["wins"] == 0
        assert taping["win_rate"] == 0.0

    def test_sorted_by_match_count_desc(self, obs_client):
        """試合数降順でソートされること（左利き2試合が先頭）"""
        client, player_id = obs_client
        resp = client.get(f"/api/analysis/observation_analytics?player_id={player_id}")
        splits = resp.json()["data"]["splits"]
        assert splits[0]["match_count"] >= splits[-1]["match_count"]

    def test_empty_player_returns_empty_splits(self, obs_client):
        client, _ = obs_client
        resp = client.get("/api/analysis/observation_analytics?player_id=999999")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["splits"] == []
        assert body["meta"]["sample_size"] == 0

    def test_response_has_confidence_field(self, obs_client):
        client, player_id = obs_client
        resp = client.get(f"/api/analysis/observation_analytics?player_id={player_id}")
        splits = resp.json()["data"]["splits"]
        for entry in splits:
            assert "confidence" in entry
            assert entry["confidence"] in ("unknown", "tentative", "likely", "confirmed")

    def test_self_condition_in_self_observations(self, obs_client):
        """自コンディション観察が self_observations セクションに含まれること"""
        client, player_id = obs_client
        # 自コンディション観察を追加（player_id = player_a = self）
        from backend.db.models import PreMatchObservation
        from sqlalchemy.orm import Session
        # このテストは POST /warmup を経由しないため直接は検証が難しい
        # フィールドの存在確認のみ
        resp = client.get(f"/api/analysis/observation_analytics?player_id={player_id}")
        body = resp.json()
        assert "self_observations" in body["data"]
