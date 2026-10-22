"""/api/auth/me の page_access は、backend が実際に許す 'llm' だけを返す。

llm_chat.require_llm_access は admin と 'llm' ロール以外に、admin が付与した
'llm' grant を要求する。/auth/me が analyst/coach にも常に 'llm' を返すと、
ナビには出るのに API が 403 になる食い違いになる (監査 #572)。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import PlayerPageAccess, User
from backend.main import app
from backend.utils.jwt_utils import create_access_token


def _make_user(db, uid: int, role: str) -> User:
    u = User(
        id=uid, username=f"llm_pa_{uid}", role=role,
        consent_required=False, awaiting_admin_approval=False, is_test=True,
    )
    db.add(u)
    db.commit()
    return u


def _me(db, user: User) -> dict:
    token = create_access_token(user_id=user.id, role=user.role)
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200, res.text
        return res.json()
    finally:
        app.dependency_overrides.clear()


def test_analyst_without_llm_grant_does_not_get_llm_page(db_session):
    u = _make_user(db_session, 910001, "analyst")
    pages = _me(db_session, u)["page_access"]
    assert "llm" not in pages
    # 他のページは従来どおり全付与
    assert "prediction" in pages
    assert "expert_labeler" in pages


def test_coach_with_llm_grant_gets_llm_page(db_session):
    u = _make_user(db_session, 910002, "coach")
    db_session.add(PlayerPageAccess(page_key="llm", user_id=u.id))
    db_session.commit()
    assert "llm" in _me(db_session, u)["page_access"]
