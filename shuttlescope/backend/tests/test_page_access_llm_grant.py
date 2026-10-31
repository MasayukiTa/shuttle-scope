"""#572: admin が analyst / coach に 'llm' page grant を付与でき、
require_llm_access がその grant を述定で認めることを確かめる。

また、admin 以外 (coach) が analyst / coach 対象の page-access を書き換えられず、
player 対象でも admin 以外は llm を付与できない (default deny を広げない) ことを確かめる。
"""
from __future__ import annotations

from fastapi import Request

from backend.db import models as M
from backend.routers import auth as auth_router
from backend.routers import llm_chat


def _req(ip: str = "203.0.113.9") -> Request:
    scope = {
        "type": "http",
        "method": "PUT",
        "headers": [],
        "client": (ip, 50000),
        "path": "/api/auth/users/0/page-access",
    }
    return Request(scope)


def _ctx(monkeypatch, user_id, role, team_id=None, team_name=None):
    from backend.utils import auth as auth_utils
    ctx = auth_utils.AuthCtx(user_id=user_id, role=role, team_id=team_id,
                             team_name=team_name, player_id=None)
    monkeypatch.setattr(auth_router, "get_auth", lambda request: ctx, raising=True)
    return ctx


def _seed(db):
    db.add(M.Team(id=1, display_id="T1", name="TeamOne"))
    db.add(M.User(id=1, username="root", role="admin", consent_required=False))
    db.add(M.User(id=10, username="an", role="analyst", team_id=1, team_name="TeamOne",
                  consent_required=False))
    db.add(M.User(id=11, username="co", role="coach", team_id=1, team_name="TeamOne",
                  consent_required=False))
    db.add(M.User(id=12, username="pl", role="player", team_id=1, team_name="TeamOne",
                  consent_required=False))
    db.commit()


def _grants(db, uid):
    return {r.page_key for r in db.query(M.PlayerPageAccess)
            .filter(M.PlayerPageAccess.user_id == uid,
                    M.PlayerPageAccess.team_name.is_(None)).all()}


def test_admin_grants_llm_to_analyst_and_llm_access_passes(db_session, monkeypatch):
    _seed(db_session)
    _ctx(monkeypatch, user_id=1, role="admin")
    monkeypatch.setattr(auth_router, "get_db", lambda: db_session, raising=False)
    body = auth_router.PageAccessBody(page_keys=["llm"])
    res = auth_router.set_user_page_access(10, body, _req(), db=db_session)
    assert "llm" in res["data"]
    assert "llm" in _grants(db_session, 10)
    # require_llm_access が grant を述定で認める (analyst は role だけでは通らない)
    monkeypatch.setattr(llm_chat, "get_auth", lambda request: auth_router.get_auth(request), raising=True)
    _ctx(monkeypatch, user_id=10, role="analyst", team_id=1, team_name="TeamOne")
    ctx = llm_chat.require_llm_access(_req(), db_session)
    assert ctx.user_id == 10


def test_coach_cannot_grant_to_analyst_or_coach(db_session, monkeypatch):
    _seed(db_session)
    _ctx(monkeypatch, user_id=11, role="coach", team_id=1, team_name="TeamOne")
    body = auth_router.PageAccessBody(page_keys=["llm"])
    import pytest
    for target in (10, 11):
        with pytest.raises(Exception) as ei:
            auth_router.set_user_page_access(target, body, _req(), db=db_session)
        assert getattr(ei.value, "status_code", None) == 404


def test_non_admin_cannot_grant_llm_to_player(db_session, monkeypatch):
    _seed(db_session)
    _ctx(monkeypatch, user_id=11, role="coach", team_id=1, team_name="TeamOne")
    body = auth_router.PageAccessBody(page_keys=["llm", "prediction"])
    res = auth_router.set_user_page_access(12, body, _req(), db=db_session)
    # prediction は付与されるが llm は admin 専権なので付かない
    assert "prediction" in res["data"]
    assert "llm" not in res["data"]
    assert "llm" not in _grants(db_session, 12)
