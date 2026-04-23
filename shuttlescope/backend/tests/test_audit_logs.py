"""Phase B-5 audit log 閲覧エンドポイントのテスト。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


ADMIN_USER = "admin_al"
ADMIN_PASS = "AuditAdmin1!"


@pytest.fixture()
def client(test_engine, monkeypatch):
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

    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", ADMIN_PASS)
    from backend.config import settings
    settings.BOOTSTRAP_ADMIN_USERNAME = ADMIN_USER
    settings.BOOTSTRAP_ADMIN_PASSWORD = ADMIN_PASS
    from backend.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={
        "grant_type": "credential", "identifier": username, "password": password,
    })
    assert r.status_code == 200, r.text
    return r.json()


class TestAuditLogList:
    def test_admin_can_list_and_filter(self, client):
        data = _login(client, ADMIN_USER, ADMIN_PASS)
        access = data["access_token"]

        # 失敗ログインを 1 件挟む（監査行が 1 件増えるはず）
        client.post("/api/auth/login", json={
            "grant_type": "credential", "identifier": ADMIN_USER, "password": "bogus",
        })

        resp = client.get(
            "/api/auth/audit-logs?limit=50",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200
        rows = resp.json()["data"]
        assert isinstance(rows, list)
        actions = [r["action"] for r in rows]
        assert "login" in actions
        assert "login_failed" in actions

        # action フィルタ
        only_failed = client.get(
            "/api/auth/audit-logs?action=login_failed",
            headers={"Authorization": f"Bearer {access}"},
        ).json()["data"]
        assert only_failed
        assert all(r["action"] == "login_failed" for r in only_failed)

    def test_non_admin_rejected(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        admin_access = admin["access_token"]
        # 別ユーザー作成
        resp = client.post(
            "/api/auth/users",
            json={"username": "analyst1", "role": "analyst",
                  "display_name": "A1", "password": "AnalystPass1!"},
            headers={"Authorization": f"Bearer {admin_access}"},
        )
        assert resp.status_code in (200, 201)
        analyst = _login(client, "analyst1", "AnalystPass1!")
        forbidden = client.get(
            "/api/auth/audit-logs",
            headers={"Authorization": f"Bearer {analyst['access_token']}"},
        )
        assert forbidden.status_code == 403

    def test_unauthenticated_rejected(self, client):
        resp = client.get("/api/auth/audit-logs")
        assert resp.status_code in (401, 403)

    def test_limit_is_clamped(self, client):
        data = _login(client, ADMIN_USER, ADMIN_PASS)
        resp = client.get(
            "/api/auth/audit-logs?limit=99999",
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
        assert resp.status_code == 200

    def test_invalid_since_returns_422(self, client):
        data = _login(client, ADMIN_USER, ADMIN_PASS)
        resp = client.get(
            "/api/auth/audit-logs?since=not-a-date",
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
        assert resp.status_code == 422
