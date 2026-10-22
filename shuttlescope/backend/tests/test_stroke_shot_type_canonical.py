"""POST/PUT /strokes keep shot_type canonical, like /strokes/batch (audit #472).

Only the two values the mobile flow uses ('serve' and the placeholder for the
unclassified last hit) are stored verbatim.
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
def rally_id(db_session):
    a = Player(name="Canon A", dominant_hand="R")
    b = Player(name="Canon B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="canon", tournament_level="practice", round="R1",
        date=date(2026, 10, 22), format="singles",
        player_a_id=a.id, player_b_id=b.id, result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    gs = GameSet(match_id=m.id, set_num=1)
    db_session.add(gs)
    db_session.flush()
    r = Rally(
        set_id=gs.id, rally_num=1, server="player_a", winner="player_a",
        end_type="unknown", rally_length=0, score_a_after=1, score_b_after=0,
    )
    db_session.add(r)
    db_session.commit()
    return r.id


def _body(num: int, shot_type: str) -> dict:
    return {"stroke_num": num, "player": "player_a", "shot_type": shot_type}


def test_post_canonicalizes_aliases_and_unknown_values(client, db_session, rally_id):
    r = client.post(f"/api/strokes?rally_id={rally_id}", json=_body(1, " Jump Smash "))
    assert r.status_code == 201, r.text
    assert r.json()["data"]["shot_type"] == "smash"
    r = client.post(f"/api/strokes?rally_id={rally_id}", json=_body(2, "not-a-real-shot"))
    assert r.status_code == 201, r.text
    assert r.json()["data"]["shot_type"] == "other"
    db_session.expire_all()
    stored = {s.stroke_num: s.shot_type for s in db_session.query(Stroke).filter_by(rally_id=rally_id)}
    assert stored == {1: "smash", 2: "other"}


def test_put_canonicalizes_shot_type(client, db_session, rally_id):
    sid = client.post(f"/api/strokes?rally_id={rally_id}", json=_body(1, "serve")).json()["data"]["id"]
    r = client.put(f"/api/strokes/{sid}", json=_body(1, "custom-made-up"))
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.get(Stroke, sid).shot_type == "other"


def test_mobile_serve_value_is_kept(client, rally_id):
    r = client.post(f"/api/strokes?rally_id={rally_id}", json=_body(1, "serve"))
    assert r.status_code == 201, r.text
    assert r.json()["data"]["shot_type"] == "serve"


def test_pass2_pending_final_placeholder_is_still_accepted(client, db_session, rally_id):
    r = client.post(f"/api/strokes?rally_id={rally_id}", json=_body(9999, "__final_pending"))
    assert r.status_code == 201, r.text
    sid = r.json()["data"]["id"]
    # Pass 3 renumbers it with the placeholder still in the body
    r = client.put(f"/api/strokes/{sid}", json=_body(3, "__final_pending"))
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.get(Stroke, sid).shot_type == "__final_pending"


def test_resend_of_the_same_alias_is_idempotent(client, rally_id):
    first = client.post(f"/api/strokes?rally_id={rally_id}", json=_body(1, "Jump Smash"))
    again = client.post(f"/api/strokes?rally_id={rally_id}", json=_body(1, "Jump Smash"))
    assert first.status_code == 201 and again.status_code == 201, again.text
    assert first.json()["data"]["id"] == again.json()["data"]["id"]
