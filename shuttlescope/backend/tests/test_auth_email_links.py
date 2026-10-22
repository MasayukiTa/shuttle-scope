"""Links in invitation / password reset / verification emails must be HashRouter URLs (audit 915).

The SPA reads its route and query string from the part after '#'. A link without it is
served at '/' and the token never reaches the target page. All values are dummy.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.db import models as M
from backend.db.database import get_db
from backend.main import app, AdminWriteRateLimitMiddleware
from backend.routers import auth as auth_module
from backend.routers import auth_email
from backend.utils import jwt_utils

ADMIN_ID = 931
TARGET_ID = 932


@pytest.fixture()
def api(db_session, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "ss_password_reset_enabled", 1, raising=False)
    monkeypatch.setattr(settings, "ss_app_base_url", "https://app.example.test", raising=False)
    auth_module._IP_LOGIN_TIMES.clear()
    AdminWriteRateLimitMiddleware._state.clear()
    auth_email._RATE_BUCKETS.clear()
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        auth_email, "_send_email_safe",
        lambda to, subject, body, tag=None, *a, **k: sent.append((tag or "", body)),
    )
    db_session.add(M.User(id=ADMIN_ID, username="adm931", role="admin", consent_required=False))
    db_session.add(M.User(id=TARGET_ID, username="tgt932", role="analyst", email="target932@example.com",
                          consent_required=False))
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, raise_server_exceptions=False, client=("203.0.113.93", 50000))
    c.sent = sent  # type: ignore[attr-defined]
    try:
        yield c
    finally:
        app.dependency_overrides.clear()
        AdminWriteRateLimitMiddleware._state.clear()
        auth_email._RATE_BUCKETS.clear()


def _admin():
    return {"Authorization": "Bearer " + jwt_utils.create_access_token(user_id=ADMIN_ID, role="admin")}


def _link(body: str) -> str:
    return next(w for w in body.split() if w.startswith("https://app.example.test"))


def test_invitation_link_is_a_hash_route(api):
    r = api.post("/api/auth/invitation/create", headers=_admin(),
                 json={"email": "new931@example.com", "role": "analyst"})
    assert r.status_code == 201, r.text
    (tag, body), = api.sent
    assert tag == "invitation"
    assert _link(body).startswith("https://app.example.test/#/invite?token=")


def test_password_reset_link_is_a_hash_route(api):
    r = api.post("/api/auth/password/request_reset", json={"email": "target932@example.com"})
    assert r.status_code == 200, r.text
    (tag, body), = api.sent
    assert tag == "password_reset"
    assert _link(body).startswith("https://app.example.test/#/password/reset-confirm?token=")
