"""POST /api/media/token のセキュリティゲート単体テスト。

token 内部(grants/JWT)は test_livekit_media.py で網羅済み。ここでは
「誰が token を取れるか」のゲート (認証/権限/セッション) を検証する。
LiveKit env も実セッションも不要な決定的ケースのみ (CI 安全)。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.utils.jwt_utils import create_access_token


def _bearer(role: str, user_id: int = 1) -> dict:
    tok = create_access_token(user_id=user_id, role=role, minutes=10)
    return {"Authorization": f"Bearer {tok}"}


def test_invalid_role_rejected_422():
    with TestClient(app) as client:
        r = client.post(
            "/api/media/token",
            json={"session_code": "ABC123", "role": "superuser"},
            headers=_bearer("coach"),
        )
    assert r.status_code == 422


def test_operator_requires_privileged_role_rejected():
    # player は operator ロールの token を取得できない。
    # グローバル auth ミドルウェアが先に 401 で弾く場合と、endpoint の privilege
    # チェックが 403 で弾く場合があるが、いずれも「拒否」= セキュリティ保証は成立。
    with TestClient(app) as client:
        r = client.post(
            "/api/media/token",
            json={"session_code": "ABC123", "role": "operator"},
            headers=_bearer("player", user_id=42),
        )
    assert r.status_code in (401, 403)


def test_unknown_session_404():
    # 認証済み coach + 妥当 role でも、存在しない session は 404
    with TestClient(app) as client:
        r = client.post(
            "/api/media/token",
            json={"session_code": "NOSUCHCODE", "role": "viewer"},
            headers=_bearer("coach"),
        )
    assert r.status_code == 404


def test_anonymous_rejected():
    # 認証なしは token を取れない (401/403 いずれにせよ 2xx ではない)
    with TestClient(app) as client:
        r = client.post(
            "/api/media/token",
            json={"session_code": "ABC123", "role": "viewer"},
        )
    assert r.status_code in (401, 403)
