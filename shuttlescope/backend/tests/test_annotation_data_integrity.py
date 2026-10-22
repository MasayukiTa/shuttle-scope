"""注釈データの欠損・逆転を防ぐテスト (監査 #789 / #783)。

- #789: PUT /strokes/{id} は送られた項目だけを更新する。モバイル Pass3 は 5 項目しか
        送らないため、全項目を反映すると座標・品質・由来が None / False で消えた。
- #783: video_timestamp_start > video_timestamp_end の逆転区間を保存しない。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke
from backend.main import app


@pytest.fixture()
def client(db_session):
    from backend.main import AdminWriteRateLimitMiddleware
    from backend.routers import auth as _auth_module

    AdminWriteRateLimitMiddleware._state.clear()
    _auth_module._IP_LOGIN_TIMES.clear()
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, headers={"X-Role": "admin"})
    yield c
    app.dependency_overrides.clear()
    AdminWriteRateLimitMiddleware._state.clear()


@pytest.fixture()
def game_set(db_session):
    a = Player(name="完全性A", dominant_hand="R")
    b = Player(name="完全性B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="完全性テスト",
        tournament_level="practice",
        round="R1",
        date=date(2026, 10, 22),
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    gs = GameSet(match_id=m.id, set_num=1)
    db_session.add(gs)
    db_session.flush()
    db_session.commit()
    return gs


def _rally_body(set_id: int, rally_num: int = 1, **extra) -> dict:
    body = {
        "set_id": set_id,
        "rally_num": rally_num,
        "server": "player_a",
        "winner": "player_a",
        "end_type": "unknown",
        "rally_length": 0,
        "score_a_after": 1,
        "score_b_after": 0,
    }
    body.update(extra)
    return body


class TestStrokePutKeepsUnsentFields:
    def test_shot_type_edit_does_not_wipe_other_fields(self, client, db_session, game_set):
        rally_id = client.post("/api/rallies", json=_rally_body(game_set.id)).json()["data"]["id"]
        created = client.post(
            f"/api/strokes?rally_id={rally_id}",
            json={
                "stroke_num": 1,
                "player": "player_a",
                "shot_type": "serve",
                "hit_zone": "BL",
                "land_zone": "BR",
                "hit_x": 0.25,
                "hit_y": 0.75,
                "shot_quality": "good",
                "is_backhand": True,
                "timestamp_sec": 12.5,
                "source_method": "manual",
                "hit_zone_source": "manual",
            },
        )
        assert created.status_code == 201, created.text
        stroke_id = created.json()["data"]["id"]

        # モバイル Pass3 の editShot() が送る 5 項目だけの更新
        edit = client.put(
            f"/api/strokes/{stroke_id}",
            json={
                "stroke_num": 1,
                "player": "player_a",
                "shot_type": "clear",
                "hit_zone": "BL",
                "land_zone": "BR",
            },
        )
        assert edit.status_code == 200, edit.text

        db_session.expire_all()
        row = db_session.get(Stroke, stroke_id)
        assert row.shot_type == "clear"
        assert row.hit_x == 0.25
        assert row.hit_y == 0.75
        assert row.shot_quality == "good"
        assert row.is_backhand is True
        assert row.timestamp_sec == 12.5
        assert row.source_method == "manual"
        assert row.hit_zone_source == "manual"

    def test_explicit_null_still_clears_a_field(self, client, db_session, game_set):
        rally_id = client.post("/api/rallies", json=_rally_body(game_set.id)).json()["data"]["id"]
        stroke_id = client.post(
            f"/api/strokes?rally_id={rally_id}",
            json={
                "stroke_num": 1,
                "player": "player_a",
                "shot_type": "serve",
                "land_zone": "BR",
                "shot_quality": "good",
            },
        ).json()["data"]["id"]
        edit = client.put(
            f"/api/strokes/{stroke_id}",
            json={
                "stroke_num": 1,
                "player": "player_a",
                "shot_type": "serve",
                "land_zone": "BR",
                "shot_quality": None,
            },
        )
        assert edit.status_code == 200, edit.text
        db_session.expire_all()
        assert db_session.get(Stroke, stroke_id).shot_quality is None


class TestRallyTimestampOrder:
    def test_create_with_start_after_end_is_rejected(self, client, db_session, game_set):
        res = client.post(
            "/api/rallies",
            json=_rally_body(game_set.id, video_timestamp_start=120.0, video_timestamp_end=110.0),
        )
        assert res.status_code == 422, res.text
        assert db_session.query(Rally).filter(Rally.set_id == game_set.id).count() == 0

    def test_create_with_ordered_or_missing_timestamps_is_accepted(self, client, game_set):
        ok = client.post(
            "/api/rallies",
            json=_rally_body(game_set.id, 1, video_timestamp_start=10.0, video_timestamp_end=20.0),
        )
        assert ok.status_code == 201, ok.text
        only_end = client.post(
            "/api/rallies",
            json=_rally_body(game_set.id, 2, score_a_after=2, video_timestamp_end=30.0),
        )
        assert only_end.status_code == 201, only_end.text

    def test_update_that_would_invert_the_interval_is_rejected(self, client, db_session, game_set):
        rally_id = client.post(
            "/api/rallies",
            json=_rally_body(game_set.id, video_timestamp_start=10.0, video_timestamp_end=20.0),
        ).json()["data"]["id"]
        bad = client.put(f"/api/rallies/{rally_id}", json={"video_timestamp_end": 5.0})
        assert bad.status_code == 422, bad.text
        db_session.expire_all()
        assert db_session.get(Rally, rally_id).video_timestamp_end == 20.0
        good = client.put(f"/api/rallies/{rally_id}", json={"video_timestamp_end": 25.0})
        assert good.status_code == 200, good.text
