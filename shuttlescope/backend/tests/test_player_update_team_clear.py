"""PUT /players/{id}: 明示 team=null は所属解除、team 未指定は所属を変えない。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Player, Team
from backend.main import app
from backend.utils.jwt_utils import create_access_token


def _admin_headers() -> dict[str, str]:
    token = create_access_token(user_id=9801, role="admin")
    return {"Authorization": f"Bearer {token}"}


def _client() -> TestClient:
    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


def _seed(db):
    team = Team(id=9701, display_id="TC-A", name="Team Clear A")
    db.add(team)
    db.flush()
    player = Player(id=9702, name="Clear Me", name_normalized="clear me", team_id=team.id)
    db.add(player)
    db.commit()
    return team, player


def _put(db_session, player_id: int, body: dict):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        return _client().put(f"/api/players/{player_id}", json=body, headers=_admin_headers())
    finally:
        app.dependency_overrides.clear()


def test_explicit_null_team_clears_affiliation(db_session):
    _team, player = _seed(db_session)
    response = _put(db_session, player.id, {"name": "Clear Me", "team": None})
    assert response.status_code == 200, response.text
    db_session.refresh(player)
    assert player.team_id is None


def test_omitted_team_keeps_affiliation(db_session):
    team, player = _seed(db_session)
    response = _put(db_session, player.id, {"name": "Clear Me Renamed"})
    assert response.status_code == 200, response.text
    db_session.refresh(player)
    assert player.team_id == team.id
