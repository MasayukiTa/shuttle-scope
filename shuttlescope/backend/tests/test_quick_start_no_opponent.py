"""POST /api/matches/quick-start で opponent_id を省略したとき (相手選手を自動作成する経路)。

以前は Player(team=...) が読み取り専用 property への代入になり、常に 500 になっていた。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.db import models as M
from backend.db.database import get_db
from backend.main import app
from backend.tests.test_cross_team_write_scope import TA, TB, _seed, tok


@pytest.fixture
def client(db_session):
    _seed(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, raise_server_exceptions=False, client=("203.0.113.9", 50000))
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def _post(client, kind, **over):
    body = dict(player_a_id=1, opponent_name="New Opponent", opponent_team="Other Club")
    body.update(over)
    return client.post("/api/matches/quick-start", json=body, headers=tok(kind))


def test_creates_opponent_and_match(client, db_session):
    r = _post(client, "cA")
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["opponent_created"] is True
    pid = data["match"]["player_b_id"]
    p = db_session.get(M.Player, pid)
    assert p.name == "New Opponent"
    assert p.created_via_quick_start is True
    assert p.profile_status == "provisional"
    # 他チームの名簿には入れない。登録主体だけが自チームになる
    assert p.team_id is None
    assert p.scouting_owner_team_id == TA
    assert "Other Club" in (p.notes or "")
    m = db_session.get(M.Match, data["match"]["id"])
    assert m.owner_team_id == TA


def test_without_team_name(client, db_session):
    r = _post(client, "aA", opponent_team=None)
    assert r.status_code == 201, r.text
    p = db_session.get(M.Player, r.json()["data"]["match"]["player_b_id"])
    assert p.notes is None


def test_other_team_cannot_use_foreign_player_a(client, db_session):
    before = db_session.query(M.Player).count()
    r = _post(client, "cB")
    assert r.status_code in (403, 404), r.text
    assert db_session.query(M.Player).count() == before
    assert TB != TA
