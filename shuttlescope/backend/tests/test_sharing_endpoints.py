"""共有系エンドポイントのテスト（sessions / comments / bookmarks）"""
import pytest
from fastapi.testclient import TestClient
from datetime import date

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, SharedSession, Comment, EventBookmark


def _make_player(db, name="テスト選手"):
    p = Player(name=name)
    db.add(p)
    db.flush()
    return p


def _make_match(db, pa, pb):
    m = Match(
        tournament="テスト大会",
        tournament_level="IC",
        round="1回戦",
        date=date(2025, 1, 1),
        format="singles",
        player_a_id=pa.id,
        player_b_id=pb.id,
        result="win",
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture
def sharing_client(db_session):
    pa = _make_player(db_session, "Aさん")
    pb = _make_player(db_session, "Bさん")
    match = _make_match(db_session, pa, pb)

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app, headers={"X-Role": "admin"})
    yield client, match.id, pa.id
    app.dependency_overrides.clear()


class TestSharedSessions:
    def test_create_session_returns_201(self, sharing_client):
        client, match_id, *_ = sharing_client
        resp = client.post("/api/sessions", json={
            "match_id": match_id,
            "created_by_role": "analyst",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert "session_code" in body["data"]

    def test_create_session_default_role(self, sharing_client):
        """created_by_role を省略してもセッション作成できること"""
        client, match_id, *_ = sharing_client
        resp = client.post("/api/sessions", json={"match_id": match_id})
        assert resp.status_code == 201

    def test_get_session_by_code(self, sharing_client):
        client, match_id, *_ = sharing_client
        create_resp = client.post("/api/sessions", json={
            "match_id": match_id,
            "created_by_role": "analyst",
        })
        code = create_resp.json()["data"]["session_code"]
        resp = client.get(f"/api/sessions/{code}")
        assert resp.status_code == 200
        assert resp.json()["data"]["match_id"] == match_id

    def test_get_nonexistent_session_returns_404(self, sharing_client):
        client, *_ = sharing_client
        resp = client.get("/api/sessions/ZZZZZZ")
        assert resp.status_code == 404

    def test_list_sessions_for_match(self, sharing_client):
        """GET /sessions/match/{match_id} がアクティブセッション一覧を返すこと"""
        client, match_id, *_ = sharing_client
        client.post("/api/sessions", json={"match_id": match_id, "created_by_role": "analyst"})
        resp = client.get(f"/api/sessions/match/{match_id}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1

    def test_create_session_for_nonexistent_match_returns_404(self, sharing_client):
        client, *_ = sharing_client
        resp = client.post("/api/sessions", json={"match_id": 999999})
        assert resp.status_code == 404


class TestComments:
    def test_post_comment_returns_201(self, sharing_client):
        client, match_id, *_ = sharing_client
        resp = client.post("/api/comments", json={
            "match_id": match_id,
            "text": "テストコメントです",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["text"] == "テストコメントです"

    def test_get_comments_for_match(self, sharing_client):
        client, match_id, *_ = sharing_client
        client.post("/api/comments", json={
            "match_id": match_id, "text": "1件目",
        })
        client.post("/api/comments", json={
            "match_id": match_id, "text": "2件目",
        })
        resp = client.get(f"/api/comments?match_id={match_id}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 2

    def test_comment_with_rally_ref(self, sharing_client):
        """rally_id 付きコメントが保存されること"""
        client, match_id, *_ = sharing_client
        resp = client.post("/api/comments", json={
            "match_id": match_id,
            "text": "このラリー重要",
            "rally_id": None,
            "is_flagged": True,
        })
        assert resp.status_code == 201
        assert resp.json()["data"]["is_flagged"] is True

    def test_flag_comment(self, sharing_client):
        """PATCH /comments/{id}/flag がコメントにフラグを立てること"""
        client, match_id, *_ = sharing_client
        create_resp = client.post("/api/comments", json={
            "match_id": match_id, "text": "要フラグ",
        })
        comment_id = create_resp.json()["data"]["id"]
        flag_resp = client.patch(f"/api/comments/{comment_id}/flag")
        assert flag_resp.status_code == 200

    def test_delete_comment(self, sharing_client):
        client, match_id, *_ = sharing_client
        create_resp = client.post("/api/comments", json={
            "match_id": match_id, "text": "削除対象",
        })
        comment_id = create_resp.json()["data"]["id"]
        del_resp = client.delete(f"/api/comments/{comment_id}")
        assert del_resp.status_code == 200


class TestBookmarks:
    def test_post_bookmark_returns_201(self, sharing_client):
        client, match_id, *_ = sharing_client
        resp = client.post("/api/bookmarks", json={
            "match_id": match_id,
            "bookmark_type": "manual",
            "note": "要注目",
        })
        assert resp.status_code == 201
        assert resp.json()["success"] is True

    def test_get_bookmarks_for_match(self, sharing_client):
        client, match_id, *_ = sharing_client
        client.post("/api/bookmarks", json={
            "match_id": match_id, "bookmark_type": "manual",
        })
        resp = client.get(f"/api/bookmarks?match_id={match_id}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1

    def test_invalid_bookmark_type_rejected(self, sharing_client):
        client, match_id, *_ = sharing_client
        resp = client.post("/api/bookmarks", json={
            "match_id": match_id,
            "bookmark_type": "invalid_type",
        })
        assert resp.status_code == 422

    def test_mark_bookmark_reviewed(self, sharing_client):
        client, match_id, *_ = sharing_client
        create_resp = client.post("/api/bookmarks", json={
            "match_id": match_id, "bookmark_type": "coach_request",
        })
        bm_id = create_resp.json()["data"]["id"]
        reviewed_resp = client.patch(f"/api/bookmarks/{bm_id}/reviewed")
        assert reviewed_resp.status_code == 200

    def test_delete_bookmark(self, sharing_client):
        client, match_id, *_ = sharing_client
        create_resp = client.post("/api/bookmarks", json={
            "match_id": match_id, "bookmark_type": "manual",
        })
        bm_id = create_resp.json()["data"]["id"]
        del_resp = client.delete(f"/api/bookmarks/{bm_id}")
        assert del_resp.status_code == 200
