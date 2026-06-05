"""LLM チャット API のアクセス制御テスト (権限上昇/横移動が起きないことの検証)。"""
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import SessionLocal
from backend.db.models import PlayerPageAccess
from backend.utils.jwt_utils import create_access_token


def _hdr(uid, role="coach", team=None):
    return {"Authorization": f"Bearer {create_access_token(user_id=uid, role=role, minutes=10)}"}


def _grant_user(uid):
    with SessionLocal() as db:
        db.add(PlayerPageAccess(page_key="llm", user_id=uid))
        db.commit()


def test_ungranted_user_is_forbidden():
    with TestClient(app) as client:
        r = client.get("/api/llm/conversations", headers=_hdr(9001, role="coach"))
    assert r.status_code == 403


def test_granted_user_can_create_and_list():
    _grant_user(9002)
    with TestClient(app) as client:
        c = client.post("/api/llm/conversations", json={"title": "t"}, headers=_hdr(9002))
        assert c.status_code == 201, c.text
        cid = c.json()["id"]
        lst = client.get("/api/llm/conversations", headers=_hdr(9002)).json()
        assert any(x["id"] == cid for x in lst["conversations"])


def test_admin_has_access_without_grant():
    with TestClient(app) as client:
        r = client.get("/api/llm/conversations", headers=_hdr(1, role="admin"))
    assert r.status_code == 200


def test_user_level_grant_does_not_leak_to_other_user():
    """user 9003 に grant しても、grant 無しの 9004 (team 無し) は 403 のまま
    (team_name IS NULL の OR マッチ漏洩が無いこと)。"""
    _grant_user(9003)
    with TestClient(app) as client:
        r = client.get("/api/llm/conversations", headers=_hdr(9004, role="coach"))
    assert r.status_code == 403


def test_idor_other_users_conversation_is_404():
    _grant_user(9005)
    _grant_user(9006)
    with TestClient(app) as client:
        c = client.post("/api/llm/conversations", json={}, headers=_hdr(9005))
        cid = c.json()["id"]
        # 別ユーザ (granted) でも他人の会話は 404
        r = client.get(f"/api/llm/conversations/{cid}/messages", headers=_hdr(9006))
    assert r.status_code == 404


def test_message_requires_provider_configured():
    """プロバイダ未設定 (テスト環境に API キー無し) なら送信は 503。ネットワークは張らない。"""
    _grant_user(9007)
    with TestClient(app) as client:
        c = client.post("/api/llm/conversations", json={}, headers=_hdr(9007))
        cid = c.json()["id"]
        r = client.post(f"/api/llm/conversations/{cid}/messages",
                        json={"content": "hello"}, headers=_hdr(9007))
    assert r.status_code in (503, 429)
