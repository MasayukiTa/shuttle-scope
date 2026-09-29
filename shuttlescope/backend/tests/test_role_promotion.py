"""analyst/coach による自チーム role 変更 (自分の権限レベルまで) の検証。

仕様:
- analyst/coach は自チーム所属ユーザの role を、自分のレベル以下に変更できる。
- 上位ロール付与・admin 付与・自分自身・他チームは不可 (403)。
"""
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import User
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token

_TEAM = 9001


def _tok(role: str, user_id: int, team_id: int = _TEAM, team_name: str = "Test Team") -> str:
    return create_access_token(
        user_id=user_id, role=role, player_id=None,
        team_name=team_name, team_id=team_id,
    )


def _seed(db):
    db.query(User).delete()
    db.add_all([
        User(id=200, username="an_op", role="analyst", display_name="An",
             hashed_credential=_hash_password("x"), team_id=_TEAM, team_name="Test Team"),
        User(id=201, username="co_op", role="coach", display_name="Co",
             hashed_credential=_hash_password("x"), team_id=_TEAM, team_name="Test Team"),
        User(id=202, username="pl_t", role="player", display_name="Pl",
             hashed_credential=_hash_password("x"), team_id=_TEAM, team_name="Test Team"),
        User(id=203, username="pl_x", role="player", display_name="Plx",
             hashed_credential=_hash_password("x"), team_id=8888, team_name="Other"),
    ])
    db.commit()


def _put(db, token, tid, body):
    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app, raise_server_exceptions=False)
        return c.put(f"/api/auth/users/{tid}", json=body,
                     headers={"Authorization": f"Bearer {token}"})
    finally:
        app.dependency_overrides.clear()


class TestRolePromotionOwnTeam:
    def test_analyst_promotes_own_team_player_to_coach(self, db_session):
        _seed(db_session)
        r = _put(db_session, _tok("analyst", 200), 202, {"role": "coach"})
        assert r.status_code == 200, r.text[:200]
        db_session.expire_all()
        assert db_session.get(User, 202).role == "coach"

    def test_analyst_can_grant_up_to_own_level(self, db_session):
        _seed(db_session)
        r = _put(db_session, _tok("analyst", 200), 202, {"role": "analyst"})
        assert r.status_code == 200, r.text[:200]
        db_session.expire_all()
        assert db_session.get(User, 202).role == "analyst"

    def test_coach_promotes_own_team_player_to_coach(self, db_session):
        _seed(db_session)
        r = _put(db_session, _tok("coach", 201), 202, {"role": "coach"})
        assert r.status_code == 200, r.text[:200]
        db_session.expire_all()
        assert db_session.get(User, 202).role == "coach"

    def test_coach_cannot_grant_above_own_level(self, db_session):
        _seed(db_session)
        r = _put(db_session, _tok("coach", 201), 202, {"role": "analyst"})
        assert r.status_code == 403
        db_session.expire_all()
        assert db_session.get(User, 202).role == "player"

    def test_cannot_grant_admin(self, db_session):
        _seed(db_session)
        r = _put(db_session, _tok("analyst", 200), 202, {"role": "admin"})
        assert r.status_code == 403
        db_session.expire_all()
        assert db_session.get(User, 202).role == "player"

    def test_cannot_change_cross_team(self, db_session):
        _seed(db_session)
        r = _put(db_session, _tok("analyst", 200), 203, {"role": "coach"})
        assert r.status_code == 403
        db_session.expire_all()
        assert db_session.get(User, 203).role == "player"

    def test_cannot_change_own_role(self, db_session):
        _seed(db_session)
        r = _put(db_session, _tok("analyst", 200), 200, {"role": "coach"})
        assert r.status_code == 403
        db_session.expire_all()
        assert db_session.get(User, 200).role == "analyst"
