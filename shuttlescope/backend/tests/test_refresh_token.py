"""Phase B-1 refresh token テスト。

- /auth/login が refresh_token を返すこと
- /auth/refresh が rotation 方式で新 access + refresh を返すこと
- 使用済み refresh の再提示で reuse 検知・chain revoke
- /auth/logout で refresh が revoke されること
"""
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(test_engine, monkeypatch):
    # 他テストで作成した users / refresh_tokens を除去し、bootstrap admin を再シード可能にする
    from backend.routers import auth as _auth_module
    _auth_module._IP_LOGIN_TIMES.clear()
    from backend.db.models import User, RefreshToken, RevokedToken, AccessLog
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=test_engine)
    with Session() as s:
        s.query(AccessLog).delete()
        s.query(RefreshToken).delete()
        s.query(RevokedToken).delete()
        s.query(User).delete()
        s.commit()

    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", "admin_rt")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "RefreshTest123!")
    from backend.config import settings
    settings.BOOTSTRAP_ADMIN_USERNAME = "admin_rt"
    settings.BOOTSTRAP_ADMIN_PASSWORD = "RefreshTest123!"
    from backend.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _login(client) -> dict:
    resp = client.post(
        "/api/auth/login",
        json={
            "grant_type": "credential",
            "identifier": "admin_rt",
            "password": "RefreshTest123!",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestLoginReturnsRefreshToken:
    def test_login_returns_refresh_token(self, client):
        data = _login(client)
        assert data.get("access_token")
        assert data.get("refresh_token")
        assert len(data["refresh_token"]) >= 32


class TestRefreshRotation:
    def test_refresh_returns_new_access_and_refresh(self, client):
        data = _login(client)
        rt = data["refresh_token"]
        resp = client.post("/api/auth/refresh", json={"refresh_token": rt})
        assert resp.status_code == 200
        j = resp.json()
        assert j["access_token"]
        assert j["refresh_token"]
        assert j["refresh_token"] != rt

    def test_refresh_invalid_returns_401(self, client):
        resp = client.post("/api/auth/refresh", json={"refresh_token": "bogus-token"})
        assert resp.status_code == 401

    def test_reuse_detection_revokes_chain(self, client):
        """revoke 済み refresh の再提示で 401、かつ回転後の新 refresh も無効化される"""
        data = _login(client)
        rt1 = data["refresh_token"]
        # 1 回目の rotation → rt2 発行、rt1 は revoke
        r = client.post("/api/auth/refresh", json={"refresh_token": rt1})
        assert r.status_code == 200
        rt2 = r.json()["refresh_token"]

        # rt1 を再提示（reuse） → 401 + chain 全体 revoke
        reuse = client.post("/api/auth/refresh", json={"refresh_token": rt1})
        assert reuse.status_code == 401

        # chain が revoke されたので rt2 も無効
        after = client.post("/api/auth/refresh", json={"refresh_token": rt2})
        assert after.status_code == 401


class TestLogoutRevokesRefresh:
    def test_logout_revokes_refresh_token(self, client):
        data = _login(client)
        rt = data["refresh_token"]
        access = data["access_token"]
        # logout with refresh_token body
        resp = client.post(
            "/api/auth/logout",
            json={"refresh_token": rt},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200
        # refresh は revoke 済みなので再発行できない
        r2 = client.post("/api/auth/refresh", json={"refresh_token": rt})
        assert r2.status_code == 401
