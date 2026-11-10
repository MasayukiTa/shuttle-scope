"""モバイル注釈の重複・競合入力のテスト (監査 #761 / #764 / #766)。

- #761: 同じラリーへ Pass2 を再実行すると stroke_num=1/9999 が二重に入った。
- #764: 複数端末が同じラリー番号へ異なる内容を送ると、先勝ち行を「成功」と返し、
        負けた端末の入力が無警告で消えた。再送(同じ内容)は冪等のまま。
- #766: POST /rallies は score_before を保存せず、2 ラリー目以降も 0-0 になった。
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
    a = Player(name="競合A", dominant_hand="R")
    b = Player(name="競合B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="競合テスト",
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


def _rally_body(set_id: int, rally_num: int, *, winner: str = "player_a", a: int = 1, b: int = 0) -> dict:
    return {
        "set_id": set_id,
        "rally_num": rally_num,
        "server": "player_a",
        "winner": winner,
        "end_type": "unknown",
        "rally_length": 0,
        "score_a_after": a,
        "score_b_after": b,
    }


def _stroke_body(num: int, *, shot_type: str = "serve", player: str = "player_a", hit_zone: str = "BL") -> dict:
    return {
        "stroke_num": num,
        "player": player,
        "shot_type": shot_type,
        "hit_zone": hit_zone,
        "land_zone": "BR",
    }


def _make_rally(client, game_set) -> int:
    r = client.post("/api/rallies", json=_rally_body(game_set.id, 1))
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


class TestRallyPayloadConflict:
    def test_different_winner_for_same_number_is_a_conflict(self, client, game_set):
        first = client.post("/api/rallies", json=_rally_body(game_set.id, 1, winner="player_a", a=1, b=0))
        assert first.status_code == 201
        second = client.post("/api/rallies", json=_rally_body(game_set.id, 1, winner="player_b", a=0, b=1))
        assert second.status_code == 409, second.text
        detail = second.json()["detail"]
        assert detail["code"] == "RALLY_CONFLICT"
        assert set(detail["differences"]) == {"winner", "score_a_after", "score_b_after"}
        assert detail["existing"]["id"] == first.json()["data"]["id"]

    def test_identical_retry_is_still_idempotent(self, client, game_set):
        first = client.post("/api/rallies", json=_rally_body(game_set.id, 1))
        second = client.post("/api/rallies", json=_rally_body(game_set.id, 1))
        assert second.status_code in (200, 201)
        assert second.json()["data"]["id"] == first.json()["data"]["id"]

    def test_conflict_does_not_replace_the_stored_row(self, client, db_session, game_set):
        client.post("/api/rallies", json=_rally_body(game_set.id, 1, winner="player_a", a=1, b=0))
        client.post("/api/rallies", json=_rally_body(game_set.id, 1, winner="player_b", a=0, b=1))
        rows = db_session.query(Rally).filter(Rally.set_id == game_set.id).all()
        assert len(rows) == 1
        assert rows[0].winner == "player_a"


class TestRallyScoreBefore:
    def test_second_rally_gets_score_before_from_previous_after(self, client, db_session, game_set):
        client.post("/api/rallies", json=_rally_body(game_set.id, 1, winner="player_a", a=1, b=0))
        r2 = client.post("/api/rallies", json=_rally_body(game_set.id, 2, winner="player_b", a=1, b=1))
        assert r2.status_code == 201, r2.text
        row = db_session.get(Rally, r2.json()["data"]["id"])
        assert (row.score_a_before, row.score_b_before) == (1, 0)

    def test_first_rally_starts_from_zero(self, client, db_session, game_set):
        r1 = client.post("/api/rallies", json=_rally_body(game_set.id, 1))
        row = db_session.get(Rally, r1.json()["data"]["id"])
        assert (row.score_a_before, row.score_b_before) == (0, 0)


class TestStrokeNumberDuplicates:
    def test_rerunning_pass2_with_different_zones_is_rejected(self, client, db_session, game_set):
        rally_id = _make_rally(client, game_set)
        ok = client.post(f"/api/strokes?rally_id={rally_id}", json=_stroke_body(1))
        assert ok.status_code == 201, ok.text
        again = client.post(f"/api/strokes?rally_id={rally_id}", json=_stroke_body(1, hit_zone="BC"))
        assert again.status_code == 409, again.text
        assert again.json()["detail"]["code"] == "STROKE_NUM_CONFLICT"
        rows = db_session.query(Stroke).filter(Stroke.rally_id == rally_id, Stroke.stroke_num == 1).all()
        assert len(rows) == 1

    def test_final_sentinel_cannot_be_duplicated(self, client, db_session, game_set):
        rally_id = _make_rally(client, game_set)
        body = _stroke_body(9999, shot_type="__final_pending", player="player_b")
        assert client.post(f"/api/strokes?rally_id={rally_id}", json=body).status_code == 201
        second = client.post(f"/api/strokes?rally_id={rally_id}", json={**body, "land_zone": "BC"})
        assert second.status_code == 409
        count = db_session.query(Stroke).filter(Stroke.rally_id == rally_id, Stroke.stroke_num == 9999).count()
        assert count == 1

    def test_identical_resend_returns_the_existing_row(self, client, db_session, game_set):
        rally_id = _make_rally(client, game_set)
        first = client.post(f"/api/strokes?rally_id={rally_id}", json=_stroke_body(1))
        second = client.post(f"/api/strokes?rally_id={rally_id}", json=_stroke_body(1))
        assert second.status_code in (200, 201)
        assert second.json()["data"]["id"] == first.json()["data"]["id"]
        assert db_session.query(Stroke).filter(Stroke.rally_id == rally_id).count() == 1

    def test_same_number_in_another_rally_is_fine(self, client, game_set):
        r1 = _make_rally(client, game_set)
        r2 = client.post("/api/rallies", json=_rally_body(game_set.id, 2, a=2, b=0)).json()["data"]["id"]
        assert client.post(f"/api/strokes?rally_id={r1}", json=_stroke_body(1)).status_code == 201
        assert client.post(f"/api/strokes?rally_id={r2}", json=_stroke_body(1)).status_code == 201

    def test_put_renumber_onto_an_occupied_number_is_rejected(self, client, game_set):
        rally_id = _make_rally(client, game_set)
        client.post(f"/api/strokes?rally_id={rally_id}", json=_stroke_body(1))
        final = client.post(
            f"/api/strokes?rally_id={rally_id}",
            json=_stroke_body(9999, shot_type="__final_pending", player="player_b"),
        ).json()["data"]
        clash = client.put(
            f"/api/strokes/{final['id']}",
            json=_stroke_body(1, shot_type="__final_pending", player="player_b"),
        )
        assert clash.status_code == 409
        free = client.put(
            f"/api/strokes/{final['id']}",
            json=_stroke_body(2, shot_type="__final_pending", player="player_b"),
        )
        assert free.status_code == 200, free.text
