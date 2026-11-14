"""players.height_cm の round-trip / validation 回帰テスト。

height_cm は選手プロフィールの任意属性 (nullable Integer)。
birth_year / world_ranking と同じく team スコープ内の create/update で
永続化され、/api/players 応答に現れることを確かめる。
体組成 (Condition.weight_kg, field_sensitivity Tier3) とは別系統で、
public/shared/export surface に出さない点は test_player_output_privacy.py 側で担保。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Player, Team
from backend.main import app
from backend.utils.jwt_utils import create_access_token

_TEAM_ID = 9751


def _admin_headers() -> dict[str, str]:
    token = create_access_token(user_id=9851, role="admin", team_name="HT", team_id=_TEAM_ID)
    return {"Authorization": f"Bearer {token}"}


def _client() -> TestClient:
    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


def _seed_team(db):
    team = Team(id=_TEAM_ID, display_id="HT-A", name="Height Team")
    db.add(team)
    db.commit()
    return team


def _with_db(db_session, fn):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        return fn()
    finally:
        app.dependency_overrides.clear()


def test_create_persists_height_cm(db_session):
    _seed_team(db_session)
    body = {"name": "Tall One", "team": "Height Team", "height_cm": 188}
    r = _with_db(db_session, lambda: _client().post(
        "/api/players", json=body, headers=_admin_headers()))
    assert r.status_code in (200, 201), r.text
    data = r.json()["data"]
    assert data["height_cm"] == 188
    pid = data["id"]
    row = db_session.get(Player, pid)
    assert row.height_cm == 188


def test_create_without_height_is_null(db_session):
    _seed_team(db_session)
    body = {"name": "No Height", "team": "Height Team"}
    r = _with_db(db_session, lambda: _client().post(
        "/api/players", json=body, headers=_admin_headers()))
    assert r.status_code in (200, 201), r.text
    data = r.json()["data"]
    assert data["height_cm"] is None


def test_update_sets_and_clears_height_cm(db_session):
    _seed_team(db_session)
    player = Player(id=9752, name="Edit Me", name_normalized="edit me", team_id=_TEAM_ID)
    db_session.add(player)
    db_session.commit()

    # set
    r1 = _with_db(db_session, lambda: _client().put(
        f"/api/players/{player.id}", json={"name": "Edit Me", "height_cm": 171},
        headers=_admin_headers()))
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["height_cm"] == 171
    db_session.refresh(player)
    assert player.height_cm == 171

    # clear (明示 null)
    r2 = _with_db(db_session, lambda: _client().put(
        f"/api/players/{player.id}", json={"name": "Edit Me", "height_cm": None},
        headers=_admin_headers()))
    assert r2.status_code == 200, r2.text
    db_session.refresh(player)
    assert player.height_cm is None


def test_height_cm_out_of_range_rejected(db_session):
    _seed_team(db_session)
    for bad in (50, 300):
        r = _with_db(db_session, lambda: _client().post(
            "/api/players", json={"name": "Bad", "team": "Height Team", "height_cm": bad},
            headers=_admin_headers()))
        assert r.status_code == 422, (bad, r.text)
