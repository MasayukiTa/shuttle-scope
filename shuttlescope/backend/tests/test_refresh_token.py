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


class TestRotationIdempotency:
    """fix/auth-session-persist: rotation の冪等化。

    ネットワーク断で応答を取りこぼしたクライアントが同じ旧 refresh を再送したり、
    タブ複製で二重に rotation が走ったりしても、猶予窓 (REFRESH_ROTATION_GRACE_SECONDS)
    の内側なら chain を壊さず同じ後継 refresh を返す。窓を過ぎた再提示は従来どおり
    reuse 扱いで一族を revoke する。

    冪等化は後継 refresh の平文を Fernet 暗号化して保存できる場合のみ有効。テスト環境は
    既定で鍵未設定なので、このクラスでは局所的に鍵を設定し field_crypto キャッシュを
    リセットする。
    """

    @pytest.fixture()
    def _field_key(self, monkeypatch):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode("ascii")
        monkeypatch.setenv("SS_FIELD_ENCRYPTION_KEY", key)
        from backend.config import settings
        monkeypatch.setattr(settings, "ss_field_encryption_key", key, raising=False)
        import backend.utils.field_crypto as fc
        # モジュール内キャッシュをリセットして、設定した鍵が確実に使われるようにする。
        monkeypatch.setattr(fc, "_fernet_cache", None, raising=False)
        monkeypatch.setattr(fc, "_warned_no_key", False, raising=False)
        yield key
        monkeypatch.setattr(fc, "_fernet_cache", None, raising=False)

    def test_within_grace_replays_same_successor(self, client, _field_key):
        """猶予窓内に旧 refresh を再送すると、chain を壊さず同じ後継を返す。"""
        data = _login(client)
        rt1 = data["refresh_token"]
        r = client.post("/api/auth/refresh", json={"refresh_token": rt1})
        assert r.status_code == 200, r.text
        rt2 = r.json()["refresh_token"]

        # 旧 refresh (rt1) を猶予窓内に再提示 → reuse ではなく冪等 replay。
        replay = client.post("/api/auth/refresh", json={"refresh_token": rt1})
        assert replay.status_code == 200, replay.text
        # 返ってくる後継は 1 回目の rotation と同じ token (冪等)。
        assert replay.json()["refresh_token"] == rt2

        # chain は壊れていないので、後継 rt2 は引き続き rotate できる。
        r3 = client.post("/api/auth/refresh", json={"refresh_token": rt2})
        assert r3.status_code == 200, r3.text
        assert r3.json()["refresh_token"] != rt2

    def test_past_grace_revokes_chain(self, client, _field_key, monkeypatch):
        """猶予を過ぎた再提示は従来どおり reuse 扱いで chain を revoke する。"""
        import backend.utils.jwt_utils as ju
        # 猶予窓を 0 秒にして、どんな再提示も「猶予外」とみなさせる。
        monkeypatch.setattr(ju, "REFRESH_ROTATION_GRACE_SECONDS", 0, raising=False)

        data = _login(client)
        rt1 = data["refresh_token"]
        r = client.post("/api/auth/refresh", json={"refresh_token": rt1})
        assert r.status_code == 200, r.text
        rt2 = r.json()["refresh_token"]

        # 猶予外の再提示 → reuse 扱いで 401。
        reuse = client.post("/api/auth/refresh", json={"refresh_token": rt1})
        assert reuse.status_code == 401
        # chain 全体が revoke されるので、後継 rt2 も無効。
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
