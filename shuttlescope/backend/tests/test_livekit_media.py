"""LiveKit メディア統合 (Phase 1) の単体テスト — LiveKit サーバ不要 (JWT 検証のみ)。"""
from __future__ import annotations

import pytest
from jose import jwt

from backend.services.livekit_media import (
    LiveKitConfig,
    grants_for_role,
    issue_access_token,
    room_name_for,
)

_CFG = LiveKitConfig(
    url="wss://media.example.com",
    api_key="APIkey123",
    api_secret="s" * 32,
    token_ttl=3600,
)


def _decode(token: str) -> dict:
    # now=固定値で発行するため exp は過去になりうる → 検証は署名/claims のみ対象にする
    return jwt.decode(
        token, _CFG.api_secret, algorithms=["HS256"],
        options={"verify_aud": False, "verify_exp": False},
    )


class TestRoomMapping:
    def test_room_name_for_valid(self):
        assert room_name_for("WS1A2B") == "match-WS1A2B"

    @pytest.mark.parametrize("bad", ["", "has space", "a/b", "x" * 65, "drop;table"])
    def test_room_name_for_invalid_raises(self, bad):
        with pytest.raises(ValueError):
            room_name_for(bad)


class TestGrants:
    def test_operator_grants(self):
        g = grants_for_role("operator")
        assert g["canPublish"] and g["canSubscribe"] and g["canPublishData"]

    def test_camera_publish_only(self):
        g = grants_for_role("camera")
        assert g["canPublish"] and not g["canSubscribe"]

    def test_viewer_subscribe_only(self):
        g = grants_for_role("viewer")
        assert g["canSubscribe"] and not g["canPublish"]

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError):
            grants_for_role("admin")


class TestAccessToken:
    def test_token_claims_for_camera(self):
        tok = issue_access_token("ios-dev-1", "WS1A2B", "camera", cfg=_CFG, now=1_000_000)
        claims = _decode(tok)
        assert claims["iss"] == _CFG.api_key
        assert claims["sub"] == "ios-dev-1"
        assert claims["exp"] == 1_000_000 + 3600
        v = claims["video"]
        assert v["room"] == "match-WS1A2B"
        assert v["roomJoin"] is True
        assert v["canPublish"] is True and v["canSubscribe"] is False

    def test_token_viewer_subscribe_only(self):
        tok = issue_access_token("viewer-9", "WS1A2B", "viewer", cfg=_CFG, now=1_000_000)
        v = _decode(tok)["video"]
        assert v["canSubscribe"] is True and v["canPublish"] is False

    def test_token_signed_with_secret_only(self):
        """別 secret では検証が失敗する (署名鍵 = api_secret であること)。"""
        tok = issue_access_token("op", "WS1A2B", "operator", cfg=_CFG, now=1_000_000)
        with pytest.raises(Exception):
            jwt.decode(tok, "wrong-secret", algorithms=["HS256"], options={"verify_aud": False})

    def test_not_configured_raises(self):
        empty = LiveKitConfig(url="", api_key="", api_secret="")
        with pytest.raises(RuntimeError):
            issue_access_token("x", "WS1A2B", "operator", cfg=empty, now=1_000_000)

    def test_invalid_session_code_raises(self):
        with pytest.raises(ValueError):
            issue_access_token("x", "bad code", "operator", cfg=_CFG, now=1_000_000)
