"""Admin cross-team name-exposure masking + one-at-a-time reveal (PR: exposure).

Uses TestClient + temp SQLite (db_session fixture) with synthetic names only.
Proves:
  * admin list masks OTHER-team names and omits identifying fields;
  * admin own-team (and no-team) names are unmasked;
  * reveal writes an audit row and returns the real name;
  * a non-admin caller cannot reveal (403).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Player, Team
from backend.main import app
from backend.utils.jwt_utils import create_access_token

_ADMIN_TEAM_ID = 7001
_OTHER_TEAM_ID = 7002


def _admin_headers() -> dict:
    tok = create_access_token(
        user_id=501, role="admin", player_id=None,
        team_name="AdminTeam", team_id=_ADMIN_TEAM_ID,
    )
    return {"Authorization": f"Bearer {tok}"}


def _analyst_headers() -> dict:
    tok = create_access_token(
        user_id=502, role="analyst", player_id=None,
        team_name="AdminTeam", team_id=_ADMIN_TEAM_ID,
    )
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def world(db_session):
    db = db_session
    db.add(Team(id=_ADMIN_TEAM_ID, display_id="A-1", name="AdminTeam"))
    db.add(Team(id=_OTHER_TEAM_ID, display_id="O-1", name="OtherTeam"))
    db.flush()
    own = Player(
        name="Alpha Own", name_normalized="alphaown", name_en="Alpha Own",
        team_id=_ADMIN_TEAM_ID, birth_year=1990, notes="own note",
    )
    other = Player(
        name="Bravo Other", name_normalized="bravoother", name_en="Bravo Other",
        team_id=_OTHER_TEAM_ID, birth_year=1991, notes="other note",
    )
    noteam = Player(
        name="Charlie Free", name_normalized="charliefree", name_en="Charlie Free",
        team_id=None, birth_year=1992,
    )
    db.add_all([own, other, noteam])
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield {"db": db, "own": own, "other": other, "noteam": noteam}
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _by_id(rows, pid):
    return next(r for r in rows if r["id"] == pid)


def test_admin_list_masks_other_team_and_omits_identity(world, client):
    r = client.get("/api/players", headers=_admin_headers())
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    other = _by_id(rows, world["other"].id)
    assert other["masked"] is True
    assert other["name"].startswith("B")
    assert "Bravo" not in other["name"]
    assert other["name_en"] is None
    assert other["birth_year"] is None
    assert other["notes"] is None
    assert other["aliases"] == []
    assert other["team"] == "OtherTeam"
    assert other["id"] == world["other"].id


def test_admin_own_team_and_no_team_unmasked(world, client):
    r = client.get("/api/players", headers=_admin_headers())
    rows = r.json()["data"]
    own = _by_id(rows, world["own"].id)
    free = _by_id(rows, world["noteam"].id)
    assert own["masked"] is False
    assert own["name"] == "Alpha Own"
    assert own["birth_year"] == 1990
    assert free["masked"] is False
    assert free["name"] == "Charlie Free"


def test_reveal_writes_audit_and_returns_name(world, client):
    db = world["db"]
    from backend.db.models import AccessLog
    before = db.query(AccessLog).count()
    pid = world["other"].id
    r = client.post(
        f"/api/players/{pid}/reveal",
        headers=_admin_headers(),
        json={"confirm": True, "reason": "merge review"},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["name"] == "Bravo Other"
    assert data["birth_year"] == 1991
    after = db.query(AccessLog).count()
    assert after == before + 1


def test_reveal_requires_confirm(world, client):
    pid = world["other"].id
    r = client.post(
        f"/api/players/{pid}/reveal",
        headers=_admin_headers(),
        json={"confirm": False},
    )
    assert r.status_code == 400, r.text


def test_non_admin_cannot_reveal(world, client):
    pid = world["other"].id
    r = client.post(
        f"/api/players/{pid}/reveal",
        headers=_analyst_headers(),
        json={"confirm": True},
    )
    assert r.status_code == 403, r.text
