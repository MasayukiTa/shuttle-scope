"""Regression tests for the demo role's player_id scope on growth_snapshot.

Review finding auth-01: GET /api/insights/growth_snapshot let role "demo" pass
any player_id (HTTP 200) while coach / analyst / player were blocked with 403
for a player_id outside their scope. The router now applies the same
``can_access_player`` boundary to demo, so a demo user may only read a player
in its own (demo) team; a foreign player_id fails closed with 403.

Setup style follows backend/tests/test_authenticated_is_not_authorised.py: the
handler is called directly rather than through TestClient, because
PlayerAccessControlMiddleware would otherwise short-circuit the request before
the router's own role check runs. The demo boundary is enforced in the router,
so exercising the handler proves the fix independently of the middleware.

Rows set every NOT NULL column that has no default (Team.name, Player.name,
User.username/role).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.db.models import Player, Team, User
from backend.routers.auth import _hash_password
from backend.routers import insights as insights_router
from backend.routers.insights import get_growth_snapshot
from backend.utils.auth import AuthCtx

DEMO_TEAM_ID = 7801
REAL_TEAM_ID = 7802
DEMO_PLAYER_ID = 7811
REAL_PLAYER_ID = 7812
DEMO_UID = 7821


@pytest.fixture()
def seeded(db_session):
    """A demo team with its own player, plus a real team with a foreign player."""
    db_session.add(Team(id=DEMO_TEAM_ID, display_id="__demo__", name="DEMO"))
    db_session.add(Team(id=REAL_TEAM_ID, display_id="REAL-7802", name="Real Team"))
    db_session.add(Player(id=DEMO_PLAYER_ID, name="デモ太郎", team_id=DEMO_TEAM_ID))
    db_session.add(Player(id=REAL_PLAYER_ID, name="実選手", team_id=REAL_TEAM_ID))
    db_session.add(User(
        id=DEMO_UID, username="demo_scope_user", role="demo", display_name="Demo",
        hashed_credential=_hash_password("pw"), team_id=DEMO_TEAM_ID,
        player_id=DEMO_PLAYER_ID, consent_required=False,
    ))
    db_session.commit()
    yield db_session


def _demo_ctx():
    # A demo user: team scoped to the demo team, not admin, not player.
    return AuthCtx("demo", DEMO_PLAYER_ID, None, user_id=DEMO_UID, team_id=DEMO_TEAM_ID)


class TestDemoScopeOnGrowthSnapshot:
    def test_demo_with_a_foreign_player_id_gets_403(self, seeded):
        # demo asking for a player in another team -> can_access_player False -> 403.
        ctx = _demo_ctx()
        with pytest.raises(HTTPException) as err:
            get_growth_snapshot(
                request=None, player_id=REAL_PLAYER_ID, period_days=30,
                lang="ja", ctx=ctx, db=seeded,
            )
        assert err.value.status_code == 403

    def test_demo_with_an_allowed_player_id_still_gets_200(self, seeded):
        # demo asking for a player in its own demo team -> allowed -> 200 payload.
        ctx = _demo_ctx()
        body = get_growth_snapshot(
            request=None, player_id=DEMO_PLAYER_ID, period_days=30,
            lang="ja", ctx=ctx, db=seeded,
        )
        assert body["meta"]["example"] is True
        assert isinstance(body["items"], list)

    def test_demo_with_an_unknown_player_id_gets_403(self, seeded):
        # A player_id that does not exist is also outside the demo scope.
        ctx = _demo_ctx()
        with pytest.raises(HTTPException) as err:
            get_growth_snapshot(
                request=None, player_id=999999, period_days=30,
                lang="ja", ctx=ctx, db=seeded,
            )
        assert err.value.status_code == 403


class TestOtherRolesUnchanged:
    """coach / analyst / player boundary behaviour is unchanged by the demo fix."""

    def test_coach_scope_is_still_checked(self, monkeypatch):
        monkeypatch.setattr(insights_router, "can_access_player",
                            lambda _ctx, _pid, _db: False)
        ctx = AuthCtx("coach", None, None, user_id=2, team_id=10)
        with pytest.raises(HTTPException) as err:
            get_growth_snapshot(request=None, player_id=1234, period_days=30,
                                lang="ja", ctx=ctx, db=object())
        assert err.value.status_code == 403

    def test_analyst_scope_is_still_checked(self, monkeypatch):
        monkeypatch.setattr(insights_router, "can_access_player",
                            lambda _ctx, _pid, _db: False)
        ctx = AuthCtx("analyst", None, None, user_id=3, team_id=11)
        with pytest.raises(HTTPException) as err:
            get_growth_snapshot(request=None, player_id=1234, period_days=30,
                                lang="ja", ctx=ctx, db=object())
        assert err.value.status_code == 403

    def test_analyst_in_scope_still_gets_200(self, monkeypatch):
        monkeypatch.setattr(insights_router, "can_access_player",
                            lambda _ctx, _pid, _db: True)
        ctx = AuthCtx("analyst", None, None, user_id=4, team_id=12)
        body = get_growth_snapshot(request=None, player_id=1234, period_days=30,
                                   lang="ja", ctx=ctx, db=object())
        assert body["meta"]["example"] is True
        assert isinstance(body["items"], list)

    def test_player_cannot_read_someone_elses(self):
        ctx = AuthCtx("player", 555, None, user_id=5, team_id=None)
        with pytest.raises(HTTPException) as err:
            get_growth_snapshot(request=None, player_id=1234, period_days=30,
                                lang="ja", ctx=ctx, db=object())
        assert err.value.status_code == 403

    def test_player_can_still_read_their_own(self):
        ctx = AuthCtx("player", 1234, None, user_id=6, team_id=None)
        body = get_growth_snapshot(request=None, player_id=1234, period_days=30,
                                   lang="ja", ctx=ctx, db=object())
        assert body["meta"]["example"] is True
