"""LLM チャット API のアクセス制御テスト (権限上昇/横移動が起きないことの検証)。

アクセスは role で事前付与: admin + 'llm' ロール。それ以外 (analyst/coach/player) は
admin が付与する per-user 'llm' grant が必要。本テストは role ベース経路を検証する
(grant 経路は require_llm_access のコードパスで担保し、本番で検証)。
"""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.main import app
from backend.routers.llm_chat import CONTEXT_TOKEN_BUDGET, MAX_CONTEXT_TURNS, _windowed_history
from backend.utils.jwt_utils import create_access_token


def _hdr(uid: int, role: str):
    return {"Authorization": f"Bearer {create_access_token(user_id=uid, role=role, minutes=10)}"}


def test_llm_role_can_create_and_list():
    with TestClient(app) as client:
        c = client.post("/api/llm/conversations", json={"title": "t"}, headers=_hdr(9101, "llm"))
        assert c.status_code == 201, c.text
        cid = c.json()["id"]
        lst = client.get("/api/llm/conversations", headers=_hdr(9101, "llm")).json()
        assert any(x["id"] == cid for x in lst["conversations"])


def test_admin_has_access():
    with TestClient(app) as client:
        r = client.get("/api/llm/conversations", headers=_hdr(1, "admin"))
    assert r.status_code == 200


def test_coach_without_grant_is_forbidden():
    with TestClient(app) as client:
        r = client.get("/api/llm/conversations", headers=_hdr(9102, "coach"))
    assert r.status_code == 403


def test_player_is_forbidden():
    with TestClient(app) as client:
        r = client.get("/api/llm/conversations", headers=_hdr(9103, "player"))
    assert r.status_code == 403


def test_idor_other_users_conversation_is_404():
    with TestClient(app) as client:
        c = client.post("/api/llm/conversations", json={}, headers=_hdr(9104, "llm"))
        cid = c.json()["id"]
        # 別の llm ユーザでも他人の会話は 404
        r = client.get(f"/api/llm/conversations/{cid}/messages", headers=_hdr(9105, "llm"))
    assert r.status_code == 404


def test_admin_cannot_read_other_users_conversation():
    """会話内容は所有者のみ。admin でも他人のチャットは 404 (混在/privacy 防止)。"""
    with TestClient(app) as client:
        c = client.post("/api/llm/conversations", json={}, headers=_hdr(9106, "llm"))
        cid = c.json()["id"]
        r = client.get(f"/api/llm/conversations/{cid}/messages", headers=_hdr(1, "admin"))
    assert r.status_code == 404


def test_message_requires_provider_configured():
    """プロバイダ未設定 (テスト環境に API キー無し) なら送信は 503。ネットワークは張らない。"""
    with TestClient(app) as client:
        c = client.post("/api/llm/conversations", json={}, headers=_hdr(9107, "llm"))
        cid = c.json()["id"]
        r = client.post(f"/api/llm/conversations/{cid}/messages",
                        json={"content": "hello"}, headers=_hdr(9107, "llm"))
    assert r.status_code in (503, 429)


def test_windowed_history_token_and_count_bounded():
    turns = [SimpleNamespace(role=("user" if i % 2 == 0 else "assistant"), content="x" * 400)
             for i in range(200)]
    out = _windowed_history(turns)
    assert len(out) <= MAX_CONTEXT_TURNS
    assert out[-1].content == turns[-1].content
    tot = sum(max(1, len(m.content) // 4) for m in out)
    assert tot <= CONTEXT_TOKEN_BUDGET + 200
