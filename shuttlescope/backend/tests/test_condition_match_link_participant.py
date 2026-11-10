"""condition と試合の紐付けは、その選手が出場した試合に限る (監査 #518)。

同一チーム内の無関係な Player と Match を questionnaire / POST / PATCH で
結び付けられないこと、出場した試合 (partner を含む) は従来どおり結び付けられること。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.analysis.condition_questions import WEEKLY_REQUIRED_IDS
from backend.db.database import get_db
from backend.db.models import Condition, Match, Player
from backend.main import app


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def world(db_session):
    """A1 は試合に出ない。A2/A3 が対戦し、A4 は A2 のパートナー。"""
    players = {}
    for key in ("a1", "a2", "a3", "a4"):
        p = Player(name=f"link_{key}", dominant_hand="R")
        db_session.add(p)
        db_session.flush()
        players[key] = p
    m = Match(
        tournament="link_cup", tournament_level="domestic", round="QF",
        date=date(2026, 9, 30), format="doubles", result="win",
        player_a_id=players["a2"].id, partner_a_id=players["a4"].id,
        player_b_id=players["a3"].id,
    )
    db_session.add(m)
    db_session.commit()
    return {"players": players, "match": m}


def _qbody(player_id, match_id):
    return {
        "player_id": player_id,
        "measured_at": "2026-04-15",
        "condition_type": "weekly",
        "responses": {qid: 3 for qid in WEEKLY_REQUIRED_IDS},
        "match_id": match_id,
    }


def test_questionnaire_rejects_unrelated_player(client, world):
    r = client.post(
        "/api/conditions/questionnaire",
        json=_qbody(world["players"]["a1"].id, world["match"].id),
        headers={"X-Role": "admin"},
    )
    assert r.status_code == 422, r.text


def test_questionnaire_accepts_participant_and_partner(client, world):
    for key in ("a2", "a3", "a4"):
        r = client.post(
            "/api/conditions/questionnaire",
            json=_qbody(world["players"][key].id, world["match"].id),
            headers={"X-Role": "admin"},
        )
        assert r.status_code == 201, (key, r.text)


def test_create_rejects_unrelated_player(client, world):
    r = client.post(
        "/api/conditions",
        json={
            "player_id": world["players"]["a1"].id,
            "measured_at": "2026-09-30",
            "weight_kg": 70.0,
            "match_id": world["match"].id,
        },
        headers={"X-Role": "admin"},
    )
    assert r.status_code == 422, r.text


def test_patch_rejects_link_to_unrelated_match(client, world, db_session):
    cond = Condition(
        player_id=world["players"]["a1"].id,
        measured_at=date(2026, 9, 1),
        condition_type="weekly",
        weight_kg=60.0,
    )
    db_session.add(cond)
    db_session.commit()
    r = client.patch(
        f"/api/conditions/{cond.id}",
        json={"match_id": world["match"].id},
        headers={"X-Role": "admin"},
    )
    assert r.status_code == 422, r.text
    db_session.refresh(cond)
    assert cond.match_id is None
