"""コンディション（体調）API のテスト（Phase 1）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def player(db_session):
    p = Player(name="体調テスト選手", dominant_hand="R")
    db_session.add(p)
    db_session.flush()
    db_session.commit()
    return p


def _base_payload(player_id: int, **overrides) -> dict:
    data = {
        "player_id": player_id,
        "measured_at": "2026-04-15",
        "condition_type": "weekly",
    }
    data.update(overrides)
    return data


class TestConditionCRUD:
    def test_post_and_get_roundtrip(self, client, player):
        payload = _base_payload(
            player.id,
            weight_kg=65.3,
            body_fat_pct=12.1,
            general_comment="調子良い",
        )
        resp = client.post("/api/conditions", json=payload)
        assert resp.status_code == 201, resp.text
        created = resp.json()["data"]
        assert created["player_id"] == player.id
        assert created["weight_kg"] == 65.3
        assert created["measured_at"] == "2026-04-15"

        cid = created["id"]
        resp2 = client.get(f"/api/conditions/{cid}")
        assert resp2.status_code == 200
        got = resp2.json()["data"]
        assert got["id"] == cid
        assert got["general_comment"] == "調子良い"

    def test_hooper_index_auto_computed_when_all_present(self, client, player):
        payload = _base_payload(
            player.id,
            hooper_sleep=3,
            hooper_soreness=4,
            hooper_stress=2,
            hooper_fatigue=5,
        )
        resp = client.post("/api/conditions", json=payload)
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["hooper_index"] == 3 + 4 + 2 + 5

    def test_hooper_index_null_when_any_missing(self, client, player):
        payload = _base_payload(
            player.id,
            hooper_sleep=3,
            hooper_soreness=4,
            hooper_stress=2,
            # hooper_fatigue missing
        )
        resp = client.post("/api/conditions", json=payload)
        assert resp.status_code == 201
        assert resp.json()["data"]["hooper_index"] is None

    def test_session_load_auto_computed(self, client, player):
        payload = _base_payload(
            player.id,
            session_rpe=7,
            session_duration_min=90,
        )
        resp = client.post("/api/conditions", json=payload)
        assert resp.status_code == 201
        assert resp.json()["data"]["session_load"] == 7 * 90

    def test_session_load_null_when_duration_missing(self, client, player):
        payload = _base_payload(player.id, session_rpe=7)
        resp = client.post("/api/conditions", json=payload)
        assert resp.status_code == 201
        assert resp.json()["data"]["session_load"] is None

    def test_patch_partial_update_recomputes(self, client, player):
        # Start with 3 of 4 hooper values → index None
        payload = _base_payload(
            player.id,
            hooper_sleep=3,
            hooper_soreness=4,
            hooper_stress=2,
        )
        cid = client.post("/api/conditions", json=payload).json()["data"]["id"]

        # Patch: add fatigue → index should now be computed
        resp = client.patch(f"/api/conditions/{cid}", json={"hooper_fatigue": 6})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["hooper_fatigue"] == 6
        assert data["hooper_index"] == 3 + 4 + 2 + 6

        # Patch rpe + duration
        resp2 = client.patch(
            f"/api/conditions/{cid}",
            json={"session_rpe": 5, "session_duration_min": 60},
        )
        assert resp2.status_code == 200
        assert resp2.json()["data"]["session_load"] == 5 * 60

    def test_list_filters_and_limit(self, client, player, db_session):
        other = Player(name="別選手", dominant_hand="R")
        db_session.add(other)
        db_session.flush()
        db_session.commit()

        for d in ["2026-04-10", "2026-04-12", "2026-04-15"]:
            client.post("/api/conditions", json=_base_payload(player.id, measured_at=d))
        client.post("/api/conditions", json=_base_payload(other.id, measured_at="2026-04-14"))

        # player_id filter
        resp = client.get(f"/api/conditions?player_id={player.id}")
        assert resp.status_code == 200
        rows = resp.json()["data"]
        assert len(rows) == 3
        # descending order
        assert [r["measured_at"] for r in rows] == ["2026-04-15", "2026-04-12", "2026-04-10"]

        # since filter
        resp2 = client.get(f"/api/conditions?player_id={player.id}&since=2026-04-12")
        assert resp2.status_code == 200
        rows2 = resp2.json()["data"]
        assert len(rows2) == 2
        assert all(r["measured_at"] >= "2026-04-12" for r in rows2)

        # limit
        resp3 = client.get(f"/api/conditions?player_id={player.id}&limit=1")
        assert len(resp3.json()["data"]) == 1

    def test_post_for_missing_player_returns_404(self, client):
        resp = client.post("/api/conditions", json=_base_payload(999999))
        assert resp.status_code == 404

    def test_delete(self, client, player):
        cid = client.post("/api/conditions", json=_base_payload(player.id)).json()["data"]["id"]
        resp = client.delete(f"/api/conditions/{cid}")
        assert resp.status_code == 200
        assert client.get(f"/api/conditions/{cid}").status_code == 404
