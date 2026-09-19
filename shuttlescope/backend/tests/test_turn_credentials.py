"""S-6: TURN の資格情報が静的で、認証済みなら誰にでも配られていた。

`GET /webrtc/ice-config` は WebRTC を張る全員が叩く。認証は要るが
**ロールは問わない**（player でも通る）ので、Settings の
`turn_username` / `turn_credential` をそのまま返す実装は、
**固定の TURN 資格情報を全利用者に配っていた**ことになる。

TURN はトラフィックを中継するサーバなので、受け取った側はそれを自分の
通信の中継に使える。しかも期限が無いので、一度渡ったものは失効しない。

修正: coturn の `use-auth-secret`（REST API 方式）に合わせ、共有鍵から
HMAC-SHA1 で**期限つき・利用者ごと**の資格情報を発行する。
固定の資格情報は返さない。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.main import app
from backend.routers.tunnel import TURN_CREDENTIAL_TTL_SEC, _ephemeral_turn_credentials


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, headers={"X-Role": "admin"})
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def turn_cfg(monkeypatch):
    """Settings の読み出しを差し替える。"""
    def _apply(**overrides):
        base = {
            "turn_enabled": True,
            "turn_url": "turn:relay.example.com:3478",
            "turn_username": "static-user",
            "turn_credential": "static-password",
            "turn_static_auth_secret": "",
        }
        base.update(overrides)
        import backend.routers.settings as settings_mod
        monkeypatch.setattr(settings_mod, "_load_all", lambda _db: base)
        return base
    return _apply


def _ice(client):
    return client.get("/api/webrtc/ice-config").json()["data"]


class TestStaticCredentialsAreNeverHandedOut:
    def test_the_configured_password_does_not_appear_in_the_response(self, client, turn_cfg):
        turn_cfg(turn_static_auth_secret="shared-secret")
        body = client.get("/api/webrtc/ice-config").text
        assert "static-password" not in body
        assert "static-user" not in body

    def test_without_a_shared_secret_no_turn_is_returned(self, client, turn_cfg):
        """鍵が無いなら固定の資格情報に**戻さない**。STUN だけを返す。"""
        turn_cfg(turn_static_auth_secret="")
        data = _ice(client)
        urls = [s.get("urls") for s in data["ice_servers"]]
        assert "turn:relay.example.com:3478" not in urls
        assert all(s.get("urls", "").startswith("stun:") for s in data["ice_servers"])

    def test_and_it_says_why_rather_than_silently_dropping_turn(self, client, turn_cfg):
        turn_cfg(turn_static_auth_secret="")
        data = _ice(client)
        assert data["turn_warning"], "TURN を落としたのに理由が無い"
        assert "turn_static_auth_secret" in data["turn_warning"]

    def test_turn_enabled_reports_what_was_actually_returned(self, client, turn_cfg):
        """設定が有効でも、返せていないなら false。

        「設定上は有効」を返すと、画面は TURN が使えると信じて
        繋がらない理由を別のところに探すことになる。
        """
        turn_cfg(turn_static_auth_secret="")
        assert _ice(client)["turn_enabled"] is False
        turn_cfg(turn_static_auth_secret="shared-secret")
        assert _ice(client)["turn_enabled"] is True


class TestEphemeralCredentials:
    def test_turn_is_returned_when_the_secret_is_set(self, client, turn_cfg):
        turn_cfg(turn_static_auth_secret="shared-secret")
        data = _ice(client)
        turn = [s for s in data["ice_servers"] if s["urls"].startswith("turn:")]
        assert len(turn) == 1
        assert turn[0]["username"] and turn[0]["credential"]

    def test_the_username_carries_an_expiry_in_the_future(self, client, turn_cfg):
        turn_cfg(turn_static_auth_secret="shared-secret")
        data = _ice(client)
        turn = [s for s in data["ice_servers"] if s["urls"].startswith("turn:")][0]
        expiry_s, _, _who = turn["username"].partition(":")
        expiry = int(expiry_s)
        assert expiry > time.time()
        assert expiry <= time.time() + TURN_CREDENTIAL_TTL_SEC + 5

    def test_the_credential_is_the_hmac_coturn_will_compute(self):
        """coturn 側の検証と同じ値になること。

        ここが合っていないと、期限つきにはなったが**誰も繋がらない**。
        """
        username, credential = _ephemeral_turn_credentials("shared-secret", 42, 3600)
        expected = base64.b64encode(
            hmac.new(b"shared-secret", username.encode(), hashlib.sha1).digest()
        ).decode()
        assert credential == expected

    def test_a_different_secret_produces_a_different_credential(self):
        u1, c1 = _ephemeral_turn_credentials("secret-a", 42, 3600)
        _u2, c2 = _ephemeral_turn_credentials("secret-b", 42, 3600)
        assert c1 != c2
        assert u1  # username は鍵に依らない

    def test_turn_disabled_returns_stun_only_without_a_warning(self, client, turn_cfg):
        turn_cfg(turn_enabled=False, turn_static_auth_secret="shared-secret")
        data = _ice(client)
        assert data["turn_enabled"] is False
        assert data["turn_warning"] is None
