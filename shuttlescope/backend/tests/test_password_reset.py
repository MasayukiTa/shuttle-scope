"""Phase B-3 password change / admin reset テスト。

- /auth/password: 現在のパスワード検証必須、新パスワードはポリシー準拠
- /auth/users/{id}/reset-password: admin のみ、一時パスワード返却
- 変更/リセット後は既存 refresh が全て失効
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


ADMIN_USER = "admin_pw"
ADMIN_PASS = "AdminPass1234!"


@pytest.fixture()
def client(test_engine, monkeypatch):
    # 各テストで users/refresh_tokens/audit_logs をクリーンにし bootstrap admin を再シード
    from backend.routers import auth as _auth_module
    _auth_module._IP_LOGIN_TIMES.clear()
    from backend.db.models import User, RefreshToken, RevokedToken
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=test_engine)
    with Session() as s:
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
    resp = client.post(
        "/api/auth/login",
        json={"grant_type": "credential", "identifier": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestSelfServicePasswordChange:
    def test_change_password_success(self, client):
        login = _login(client, ADMIN_USER, ADMIN_PASS)
        access = login["access_token"]
        new_password = "NewStrongPass1!"
        resp = client.post(
            "/api/auth/password",
            json={"current_password": ADMIN_PASS, "new_password": new_password},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200

        # 旧パスワードで login 不可
        bad = client.post(
            "/api/auth/login",
            json={"grant_type": "credential", "identifier": ADMIN_USER, "password": ADMIN_PASS},
        )
        assert bad.status_code == 401

        # 新パスワードで login 可
        ok = client.post(
            "/api/auth/login",
            json={"grant_type": "credential", "identifier": ADMIN_USER, "password": new_password},
        )
        assert ok.status_code == 200

    def test_wrong_current_password_rejected(self, client):
        login = _login(client, ADMIN_USER, ADMIN_PASS)
        access = login["access_token"]
        resp = client.post(
            "/api/auth/password",
            json={"current_password": "wrong-password", "new_password": "NewStrongPass1!"},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 401

    def test_weak_new_password_rejected(self, client):
        login = _login(client, ADMIN_USER, ADMIN_PASS)
        access = login["access_token"]
        resp = client.post(
            "/api/auth/password",
            json={"current_password": ADMIN_PASS, "new_password": "short"},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 422

    def test_unauthenticated_rejected(self, client):
        resp = client.post(
            "/api/auth/password",
            json={"current_password": ADMIN_PASS, "new_password": "NewStrongPass1!"},
        )
        assert resp.status_code == 401

    def test_password_change_revokes_existing_refresh(self, client):
        login = _login(client, ADMIN_USER, ADMIN_PASS)
        access = login["access_token"]
        rt = login["refresh_token"]
        new_password = "AnotherPass1!"
        resp = client.post(
            "/api/auth/password",
            json={"current_password": ADMIN_PASS, "new_password": new_password},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200
        # 既存 refresh は失効
        r = client.post("/api/auth/refresh", json={"refresh_token": rt})
        assert r.status_code == 401


class TestAdminResetPassword:
    def _create_target_user(self, client, access: str) -> int:
        resp = client.post(
            "/api/auth/users",
            json={
                "username": "target01",
                "role": "analyst",
                "display_name": "Target",
                "password": "TargetPass1!",
            },
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code in (200, 201), resp.text
        return resp.json()["user_id"] if "user_id" in resp.json() else resp.json().get("id") or resp.json().get("data", {}).get("id")

    def test_admin_reset_returns_temp_password_and_works(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        access = admin["access_token"]
        target_id = self._create_target_user(client, access)
        assert target_id

        resp = client.post(
            f"/api/auth/users/{target_id}/reset-password",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200, resp.text
        temp = resp.json()["temporary_password"]
        assert len(temp) >= 12

        # 一時パスワードでログインできる
        ok = client.post(
            "/api/auth/login",
            json={"grant_type": "credential", "identifier": "target01", "password": temp},
        )
        assert ok.status_code == 200

        # 旧パスワードはもう使えない
        bad = client.post(
            "/api/auth/login",
            json={"grant_type": "credential", "identifier": "target01", "password": "TargetPass1!"},
        )
        assert bad.status_code == 401

    def test_non_admin_cannot_reset(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        access = admin["access_token"]
        target_id = self._create_target_user(client, access)

        # target としてログインして自分 or 他人を reset しようとする → 403
        target = _login(client, "target01", "TargetPass1!")
        resp = client.post(
            f"/api/auth/users/{target_id}/reset-password",
            headers={"Authorization": f"Bearer {target['access_token']}"},
        )
        assert resp.status_code == 403

    def test_reset_missing_user_returns_404(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        access = admin["access_token"]
        resp = client.post(
            "/api/auth/users/999999/reset-password",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 404
