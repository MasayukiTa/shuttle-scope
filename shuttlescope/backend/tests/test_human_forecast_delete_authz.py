from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import HumanForecast, Match, Player, Team, User
from backend.main import app
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token


# G5 item #687 (option A): only the creator of a human forecast (within the team)
# or an admin may delete it. Legacy rows with no creator (creator_user_id IS NULL)
# are admin-only. These tests cover: creator, other same-team user, admin, legacy
# rows, other team, and a direct handler call (bypassing middleware).


def _headers(*, user_id: int, role: str, team_id: int | None = None, team_name: str | None = None) -> dict[str, str]:
    token = create_access_token(
        user_id=user_id,
        role=role,
        team_id=team_id,
        team_name=team_name,
    )
    return {"Authorization": f"Bearer {token}"}


def _client() -> TestClient:
    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


# Middleware interprets the forecast ID in DELETE paths as a match ID.
# Match IDs therefore mirror forecast IDs so these tests reach the handler.
def _seed(db, *, own_match_id=9901, foreign_match_id=9902):
    team_a = Team(id=9601, display_id="HFD-A", name="Delete Team A")
    team_b = Team(id=9602, display_id="HFD-B", name="Delete Team B")
    db.add_all([team_a, team_b])

    db.add_all([
        Player(id=9701, name="DA1", name_normalized="da1", team_id=team_a.id),
        Player(id=9702, name="DA2", name_normalized="da2", team_id=team_a.id),
        Player(id=9703, name="DB1", name_normalized="db1", team_id=team_b.id),
        Player(id=9704, name="DB2", name_normalized="db2", team_id=team_b.id),
    ])

    # Two coaches on team A (creator + another), one coach on team B, one admin.
    db.add_all([
        User(id=9801, username="hfd_creator_a", role="coach", display_name="Creator A",
             hashed_credential=_hash_password("pw"), team_id=team_a.id, team_name=team_a.name),
        User(id=9802, username="hfd_other_a", role="coach", display_name="Other A",
             hashed_credential=_hash_password("pw"), team_id=team_a.id, team_name=team_a.name),
        User(id=9803, username="hfd_coach_b", role="coach", display_name="Coach B",
             hashed_credential=_hash_password("pw"), team_id=team_b.id, team_name=team_b.name),
        User(id=9899, username="hfd_admin", role="admin", display_name="Admin",
             hashed_credential=_hash_password("pw")),
    ])

    own_match = Match(
        id=own_match_id, tournament="Del A", tournament_level="domestic", round="QF",
        date=date(2026, 10, 1), format="singles", result="unknown",
        player_a_id=9701, player_b_id=9702, owner_team_id=team_a.id, is_public_pool=False,
    )
    foreign_match = Match(
        id=foreign_match_id, tournament="Del B", tournament_level="domestic", round="QF",
        date=date(2026, 10, 1), format="singles", result="unknown",
        player_a_id=9703, player_b_id=9704, owner_team_id=team_b.id, is_public_pool=False,
    )
    db.add_all([own_match, foreign_match])
    db.commit()
    return team_a, team_b, own_match, foreign_match


def _make_forecast(db, *, fid, match_id, player_id, team_id, creator_user_id):
    f = HumanForecast(
        id=fid, match_id=match_id, player_id=player_id, forecaster_role="coach",
        forecaster_name="x", predicted_outcome="win", team_id=team_id,
        creator_user_id=creator_user_id,
    )
    db.add(f)
    db.commit()
    return f


def _delete(fid, headers):
    return _client().delete(f"/api/prediction/human_forecast/{fid}", headers=headers)


def _is_deleted(db, fid) -> bool:
    db.expire_all()
    row = db.get(HumanForecast, fid)
    return row is not None and row.deleted_at is not None


def test_creator_can_delete_own_forecast(db_session):
    team_a, _team_b, own_match, _fm = _seed(db_session, own_match_id=9951)
    _make_forecast(db_session, fid=9951, match_id=own_match.id, player_id=9701,
                   team_id=team_a.id, creator_user_id=9801)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        resp = _delete(9951, _headers(user_id=9801, role="coach", team_id=team_a.id, team_name=team_a.name))
        assert resp.status_code == 200, resp.text
        assert _is_deleted(db_session, 9951)
    finally:
        app.dependency_overrides.clear()


def test_other_same_team_user_cannot_delete(db_session):
    team_a, _team_b, own_match, _fm = _seed(db_session, own_match_id=9952)
    _make_forecast(db_session, fid=9952, match_id=own_match.id, player_id=9701,
                   team_id=team_a.id, creator_user_id=9801)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        # 9802 is on the same team but is not the creator.
        resp = _delete(9952, _headers(user_id=9802, role="coach", team_id=team_a.id, team_name=team_a.name))
        assert resp.status_code == 403, resp.text
        assert not _is_deleted(db_session, 9952)
    finally:
        app.dependency_overrides.clear()


def test_admin_can_delete_any_forecast(db_session):
    team_a, _team_b, own_match, _fm = _seed(db_session, own_match_id=9953)
    _make_forecast(db_session, fid=9953, match_id=own_match.id, player_id=9701,
                   team_id=team_a.id, creator_user_id=9801)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        resp = _delete(9953, _headers(user_id=9899, role="admin"))
        assert resp.status_code == 200, resp.text
        assert _is_deleted(db_session, 9953)
    finally:
        app.dependency_overrides.clear()


def test_legacy_null_creator_is_admin_only(db_session):
    team_a, _team_b, own_match, _fm = _seed(db_session, own_match_id=9954)
    # Legacy row: creator_user_id is NULL.
    _make_forecast(db_session, fid=9954, match_id=own_match.id, player_id=9701,
                   team_id=team_a.id, creator_user_id=None)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        # Same-team coach cannot delete a legacy row.
        resp = _delete(9954, _headers(user_id=9801, role="coach", team_id=team_a.id, team_name=team_a.name))
        assert resp.status_code == 403, resp.text
        assert not _is_deleted(db_session, 9954)
        # Admin can.
        resp = _delete(9954, _headers(user_id=9899, role="admin"))
        assert resp.status_code == 200, resp.text
        assert _is_deleted(db_session, 9954)
    finally:
        app.dependency_overrides.clear()


def test_other_team_cannot_delete_and_cannot_learn_existence(db_session):
    team_a, team_b, _own_match, foreign_match = _seed(db_session, foreign_match_id=9955)
    # A forecast owned by team B, created by coach B (9803).
    _make_forecast(db_session, fid=9955, match_id=foreign_match.id, player_id=9703,
                   team_id=team_b.id, creator_user_id=9803)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        # Team A coach must get 404 (existence hidden across the team boundary),
        # not 403, so the cross-team row is not even acknowledged.
        resp = _delete(9955, _headers(user_id=9801, role="coach", team_id=team_a.id, team_name=team_a.name))
        assert resp.status_code == 404, resp.text
        assert not _is_deleted(db_session, 9955)
    finally:
        app.dependency_overrides.clear()


def test_delete_handler_enforces_creator_without_middleware(db_session):
    # Call the handler directly so the team-scope middleware cannot mask a
    # missing creator check inside the handler itself.
    import pytest
    from fastapi import HTTPException
    from starlette.requests import Request

    from backend.routers.human_forecast import delete_human_forecast
    from backend.utils.auth import get_auth

    team_a, _team_b, own_match, _fm = _seed(db_session, own_match_id=9956)
    _make_forecast(db_session, fid=9956, match_id=own_match.id, player_id=9701,
                   team_id=team_a.id, creator_user_id=9801)

    def _ctx(user_id, role, team_id=None, team_name=None):
        bearer = _headers(user_id=user_id, role=role, team_id=team_id, team_name=team_name)["Authorization"]
        request = Request({
            "type": "http", "method": "DELETE", "path": "/",
            "headers": [(b"authorization", bearer.encode("ascii"))],
        })
        return request, get_auth(request)

    # Non-creator same-team coach -> 403.
    req, ctx = _ctx(9802, "coach", team_a.id, team_a.name)
    with pytest.raises(HTTPException) as exc:
        delete_human_forecast(9956, request=req, db=db_session, _auth=ctx)
    assert exc.value.status_code == 403
    assert not _is_deleted(db_session, 9956)

    # Creator -> succeeds.
    req, ctx = _ctx(9801, "coach", team_a.id, team_a.name)
    out = delete_human_forecast(9956, request=req, db=db_session, _auth=ctx)
    assert out == {"success": True}
    assert _is_deleted(db_session, 9956)
