"""ウォームアップ観察エンドポイントのテスト"""
import pytest
from fastapi.testclient import TestClient
from datetime import date

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, PreMatchObservation


@pytest.fixture
def warmup_client(db_session):
    """ウォームアップテスト用クライアント"""
    player_a = Player(name="自チーム選手", dominant_hand="R")
    player_b = Player(name="相手選手", dominant_hand="L")
    db_session.add_all([player_a, player_b])
    db_session.flush()

    match = Match(
        tournament="テスト大会",
        tournament_level="IC",
        round="1回戦",
        date=date(2025, 4, 1),
        format="singles",
        player_a_id=player_a.id,
        player_b_id=player_b.id,
        result="win",
    )
    db_session.add(match)
    db_session.flush()

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app, headers={"X-Role": "admin"})
    yield client, match.id, player_a.id, player_b.id
    app.dependency_overrides.clear()


class TestWarmupGet:
    def test_get_empty_returns_200(self, warmup_client):
        client, match_id, *_ = warmup_client
        resp = client.get(f"/api/warmup/observations/{match_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []

    def test_get_nonexistent_match_returns_404(self, warmup_client):
        client, *_ = warmup_client
        resp = client.get("/api/warmup/observations/999999")
        assert resp.status_code == 404

    def test_get_returns_saved_observations(self, warmup_client):
        client, match_id, player_a_id, player_b_id = warmup_client
        # 先に1件保存
        client.post(
            f"/api/warmup/observations/{match_id}",
            json={"observations": [
                {
                    "player_id": player_b_id,
                    "observation_type": "handedness",
                    "observation_value": "L",
                    "confidence_level": "confirmed",
                }
            ]},
        )
        resp = client.get(f"/api/warmup/observations/{match_id}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["observation_type"] == "handedness"
        assert data[0]["observation_value"] == "L"


class TestWarmupPost:
    def test_post_valid_observation_returns_201(self, warmup_client):
        client, match_id, player_a_id, player_b_id = warmup_client
        resp = client.post(
            f"/api/warmup/observations/{match_id}",
            json={"observations": [
                {
                    "player_id": player_b_id,
                    "observation_type": "physical_caution",
                    "observation_value": "light",
                    "confidence_level": "likely",
                }
            ]},
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["saved_count"] == 1

    def test_post_all_allowed_types(self, warmup_client):
        client, match_id, player_a_id, player_b_id = warmup_client
        observations = [
            {"player_id": player_b_id, "observation_type": "handedness",
             "observation_value": "R", "confidence_level": "confirmed"},
            {"player_id": player_b_id, "observation_type": "physical_caution",
             "observation_value": "none", "confidence_level": "likely"},
            {"player_id": player_b_id, "observation_type": "tactical_style",
             "observation_value": "attacker", "confidence_level": "tentative"},
            {"player_id": player_b_id, "observation_type": "court_preference",
             "observation_value": "rear", "confidence_level": "tentative"},
        ]
        resp = client.post(
            f"/api/warmup/observations/{match_id}",
            json={"observations": observations},
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["saved_count"] == 4

    def test_post_invalid_type_returns_422(self, warmup_client):
        client, match_id, player_a_id, player_b_id = warmup_client
        resp = client.post(
            f"/api/warmup/observations/{match_id}",
            json={"observations": [
                {
                    "player_id": player_b_id,
                    "observation_type": "invalid_type",
                    "observation_value": "something",
                    "confidence_level": "tentative",
                }
            ]},
        )
        assert resp.status_code == 422

    def test_post_invalid_confidence_returns_422(self, warmup_client):
        client, match_id, player_a_id, player_b_id = warmup_client
        resp = client.post(
            f"/api/warmup/observations/{match_id}",
            json={"observations": [
                {
                    "player_id": player_b_id,
                    "observation_type": "handedness",
                    "observation_value": "L",
                    "confidence_level": "definitely",  # 無効
                }
            ]},
        )
        assert resp.status_code == 422

    def test_post_upsert_overwrites_existing(self, warmup_client):
        """同じ player_id + observation_type は上書きされること"""
        client, match_id, player_a_id, player_b_id = warmup_client
        # 初回
        client.post(
            f"/api/warmup/observations/{match_id}",
            json={"observations": [
                {"player_id": player_b_id, "observation_type": "handedness",
                 "observation_value": "R", "confidence_level": "tentative"}
            ]},
        )
        # 上書き
        client.post(
            f"/api/warmup/observations/{match_id}",
            json={"observations": [
                {"player_id": player_b_id, "observation_type": "handedness",
                 "observation_value": "L", "confidence_level": "confirmed"}
            ]},
        )
        resp = client.get(f"/api/warmup/observations/{match_id}")
        data = resp.json()["data"]
        # 件数は1件のまま（上書き）
        handedness_obs = [o for o in data if o["observation_type"] == "handedness"]
        assert len(handedness_obs) == 1
        assert handedness_obs[0]["observation_value"] == "L"
        assert handedness_obs[0]["confidence_level"] == "confirmed"

    def test_post_nonexistent_match_returns_404(self, warmup_client):
        client, *_, player_b_id = warmup_client
        resp = client.post(
            "/api/warmup/observations/999999",
            json={"observations": [
                {"player_id": player_b_id, "observation_type": "handedness",
                 "observation_value": "R", "confidence_level": "likely"}
            ]},
        )
        assert resp.status_code == 404

    def test_post_self_condition_type(self, warmup_client):
        """自コンディション観察タイプが保存できること"""
        client, match_id, player_a_id, player_b_id = warmup_client
        resp = client.post(
            f"/api/warmup/observations/{match_id}",
            json={"observations": [
                {
                    "player_id": player_a_id,
                    "observation_type": "self_condition",
                    "observation_value": "normal",
                    "confidence_level": "confirmed",
                }
            ]},
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["saved_count"] == 1
