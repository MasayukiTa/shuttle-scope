"""ライブソース制御 API テスト

migration 0004 で追加された機能:
- live_sources テーブル: source_kind / source_priority / suitability / source_status
- GET  /sessions/{code}/sources           — ソース一覧（優先度順）
- POST /sessions/{code}/sources           — ソース登録
- POST /sessions/{code}/sources/{id}/activate   — アクティブ化（1 ソース制限）
- POST /sessions/{code}/sources/{id}/deactivate — 非アクティブ化
"""
import pytest
from datetime import date
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, SharedSession, SessionParticipant


# ─── ヘルパー ─────────────────────────────────────────────────────────────────

def _make_match(db) -> Match:
    pa = Player(name="選手A")
    pb = Player(name="選手B")
    db.add_all([pa, pb])
    db.flush()
    m = Match(
        tournament="テスト大会",
        tournament_level="IC",
        round="1回戦",
        date=date(2026, 4, 8),
        format="singles",
        player_a_id=pa.id,
        player_b_id=pb.id,
        result="win",
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture
def source_client_with_session(db_session):
    """セッション + オペレーター参加済みクライアント"""
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app, headers={"X-Role": "analyst"})

    match = _make_match(db_session)
    db_session.commit()

    # セッション作成
    resp = client.post("/api/sessions", json={"match_id": match.id})
    assert resp.status_code == 201
    data = resp.json()["data"]
    session_code = data["session_code"]
    session_password = data.get("session_password")

    # オペレーターとして参加
    join_resp = client.post(f"/api/sessions/{session_code}/join", json={
        "role": "operator",
        "device_name": "TestPC",
        "device_type": "pc",
        "session_password": session_password,
    })
    assert join_resp.status_code == 200
    operator_id = join_resp.json()["data"]["participant_id"]

    yield client, session_code, operator_id
    app.dependency_overrides.clear()


# ─── T1: ソース登録 ───────────────────────────────────────────────────────────

class TestRegisterSource:
    def test_register_builtin_camera(self, source_client_with_session):
        """内蔵カメラを候補ソースとして登録できる"""
        client, code, _ = source_client_with_session
        resp = client.post(f"/api/sessions/{code}/sources", json={
            "source_kind": "builtin_camera",
            "source_resolution": "1280x720",
            "source_fps": 30,
        })
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["source_kind"] == "builtin_camera"
        assert data["source_status"] == "candidate"
        assert data["source_resolution"] == "1280x720"
        assert data["source_fps"] == 30

    def test_register_usb_camera(self, source_client_with_session):
        """USB カメラを登録すると suitability が自動設定される"""
        client, code, _ = source_client_with_session
        resp = client.post(f"/api/sessions/{code}/sources", json={
            "source_kind": "usb_camera",
        })
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["source_kind"] == "usb_camera"
        assert data["suitability"] in ("high", "usable", "fallback")

    def test_register_iphone_source(self, source_client_with_session):
        """iPhone WebRTC ソースを登録できる"""
        client, code, _ = source_client_with_session
        resp = client.post(f"/api/sessions/{code}/sources", json={
            "source_kind": "iphone_webrtc",
            "source_resolution": "1920x1080",
            "source_fps": 60,
        })
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["source_kind"] == "iphone_webrtc"

    def test_register_invalid_session(self, source_client_with_session):
        """存在しないセッションへの登録は 404"""
        client, _, _ = source_client_with_session
        resp = client.post("/api/sessions/ZZZZZZ/sources", json={
            "source_kind": "builtin_camera",
        })
        assert resp.status_code == 404


# ─── T2: ソース一覧（優先度順） ───────────────────────────────────────────────

class TestSourceRankingOrder:
    def test_sources_returned_in_priority_order(self, source_client_with_session):
        """複数ソース登録後、優先度昇順で返される"""
        client, code, _ = source_client_with_session

        # 3 種類登録
        for kind in ["builtin_camera", "usb_camera", "iphone_webrtc"]:
            client.post(f"/api/sessions/{code}/sources", json={"source_kind": kind})

        resp = client.get(f"/api/sessions/{code}/sources")
        assert resp.status_code == 200
        sources = resp.json()["data"]
        assert len(sources) >= 3

        priorities = [s["source_priority"] for s in sources]
        assert priorities == sorted(priorities), "優先度昇順になっていない"

    def test_empty_sources_list(self, source_client_with_session):
        """ソース未登録時は空配列を返す"""
        client, code, _ = source_client_with_session
        resp = client.get(f"/api/sessions/{code}/sources")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


# ─── T3: アクティブ化 ─────────────────────────────────────────────────────────

class TestActivateSource:
    def test_activate_source(self, source_client_with_session):
        """ソースをアクティブ化できる"""
        client, code, _ = source_client_with_session
        # 登録
        reg = client.post(f"/api/sessions/{code}/sources", json={"source_kind": "builtin_camera"})
        sid = reg.json()["data"]["id"]

        # アクティブ化
        resp = client.post(f"/api/sessions/{code}/sources/{sid}/activate")
        assert resp.status_code == 200

        # 一覧で active を確認
        sources = client.get(f"/api/sessions/{code}/sources").json()["data"]
        active = [s for s in sources if s["id"] == sid]
        assert len(active) == 1
        assert active[0]["source_status"] == "active"

    def test_only_one_active_source(self, source_client_with_session):
        """2 つ目のソースをアクティブ化すると最初のソースが candidate に戻る"""
        client, code, _ = source_client_with_session

        reg1 = client.post(f"/api/sessions/{code}/sources", json={"source_kind": "builtin_camera"})
        reg2 = client.post(f"/api/sessions/{code}/sources", json={"source_kind": "usb_camera"})
        sid1 = reg1.json()["data"]["id"]
        sid2 = reg2.json()["data"]["id"]

        # 1 つ目をアクティブ化
        client.post(f"/api/sessions/{code}/sources/{sid1}/activate")

        # 2 つ目をアクティブ化
        client.post(f"/api/sessions/{code}/sources/{sid2}/activate")

        sources = client.get(f"/api/sessions/{code}/sources").json()["data"]
        source_map = {s["id"]: s for s in sources}

        # 2 つ目が active
        assert source_map[sid2]["source_status"] == "active"
        # 1 つ目は active でない
        assert source_map[sid1]["source_status"] != "active"

    def test_activate_nonexistent_source(self, source_client_with_session):
        """存在しないソース ID への activate は 404"""
        client, code, _ = source_client_with_session
        resp = client.post(f"/api/sessions/{code}/sources/99999/activate")
        assert resp.status_code == 404


# ─── T4: 非アクティブ化 ───────────────────────────────────────────────────────

class TestDeactivateSource:
    def test_deactivate_active_source(self, source_client_with_session):
        """アクティブなソースを非アクティブ化できる"""
        client, code, _ = source_client_with_session
        reg = client.post(f"/api/sessions/{code}/sources", json={"source_kind": "usb_camera"})
        sid = reg.json()["data"]["id"]
        client.post(f"/api/sessions/{code}/sources/{sid}/activate")

        resp = client.post(f"/api/sessions/{code}/sources/{sid}/deactivate")
        assert resp.status_code == 200

        sources = client.get(f"/api/sessions/{code}/sources").json()["data"]
        source_map = {s["id"]: s for s in sources}
        assert source_map[sid]["source_status"] != "active"
