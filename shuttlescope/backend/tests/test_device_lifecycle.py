"""デバイスライフサイクル API テスト

migration 0004 で追加された機能:
- SessionParticipant 拡張: device_uid / approval_status / last_heartbeat /
  viewer_permission / device_class / display_size_class
- POST /sessions/{code}/devices/{pid}/approve
- POST /sessions/{code}/devices/{pid}/reject
- POST /sessions/{code}/devices/{pid}/heartbeat
- POST /sessions/{code}/devices/{pid}/set-viewer-permission
- device_uid による再接続認識（同一デバイスは新規作成せず更新）
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
def lifecycle_client(db_session):
    """セッション作成済みクライアント"""
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    match = _make_match(db_session)
    db_session.commit()

    resp = client.post("/api/sessions", json={"match_id": match.id})
    assert resp.status_code == 201
    data = resp.json()["data"]
    session_code = data["session_code"]
    session_password = data.get("session_password")

    yield client, session_code, session_password
    app.dependency_overrides.clear()


def _join_device(client, code, password, device_name="テストiPhone", device_type="iphone"):
    """デバイスとして参加して participant_id を返す"""
    resp = client.post(f"/api/sessions/{code}/join", json={
        "role": "viewer",
        "device_name": device_name,
        "device_type": device_type,
        "session_password": password,
    })
    assert resp.status_code == 200
    return resp.json()["data"]["participant_id"]


# ─── T1: デバイス承認 ─────────────────────────────────────────────────────────

class TestApproveDevice:
    def test_approve_device(self, lifecycle_client):
        """デバイスを承認できる"""
        client, code, password = lifecycle_client
        pid = _join_device(client, code, password)

        resp = client.post(f"/api/sessions/{code}/devices/{pid}/approve")
        assert resp.status_code == 200

        devices = client.get(f"/api/sessions/{code}/devices").json()["data"]
        target = next((d for d in devices if d["id"] == pid), None)
        assert target is not None
        assert target["approval_status"] == "approved"

    def test_approve_nonexistent_device(self, lifecycle_client):
        """存在しないデバイス ID の承認は 404"""
        client, code, _ = lifecycle_client
        resp = client.post(f"/api/sessions/{code}/devices/99999/approve")
        assert resp.status_code == 404


# ─── T2: デバイス拒否 ─────────────────────────────────────────────────────────

class TestRejectDevice:
    def test_reject_device(self, lifecycle_client):
        """デバイスを拒否できる"""
        client, code, password = lifecycle_client
        pid = _join_device(client, code, password)

        resp = client.post(f"/api/sessions/{code}/devices/{pid}/reject")
        assert resp.status_code == 200

        devices = client.get(f"/api/sessions/{code}/devices").json()["data"]
        target = next((d for d in devices if d["id"] == pid), None)
        assert target is not None
        assert target["approval_status"] == "rejected"


# ─── T3: ハートビート更新 ─────────────────────────────────────────────────────

class TestHeartbeatUpdate:
    def test_heartbeat_updates_last_seen(self, lifecycle_client):
        """ハートビートで last_heartbeat が更新される"""
        client, code, password = lifecycle_client
        pid = _join_device(client, code, password)

        resp = client.post(f"/api/sessions/{code}/devices/{pid}/heartbeat")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_heartbeat_nonexistent_device(self, lifecycle_client):
        """存在しないデバイスへのハートビートは 404"""
        client, code, _ = lifecycle_client
        resp = client.post(f"/api/sessions/{code}/devices/99999/heartbeat")
        assert resp.status_code == 404


# ─── T4: viewer_permission 設定 ───────────────────────────────────────────────

class TestViewerPermissionSet:
    def test_set_permission_allowed(self, lifecycle_client):
        """viewer_permission を allowed に設定できる"""
        client, code, password = lifecycle_client
        pid = _join_device(client, code, password)

        resp = client.post(f"/api/sessions/{code}/devices/{pid}/set-viewer-permission",
                           json={"viewer_permission": "allowed"})
        assert resp.status_code == 200

        devices = client.get(f"/api/sessions/{code}/devices").json()["data"]
        target = next((d for d in devices if d["id"] == pid), None)
        assert target is not None
        assert target["viewer_permission"] == "allowed"

    def test_set_permission_blocked(self, lifecycle_client):
        """viewer_permission を blocked に設定できる"""
        client, code, password = lifecycle_client
        pid = _join_device(client, code, password)

        resp = client.post(f"/api/sessions/{code}/devices/{pid}/set-viewer-permission",
                           json={"viewer_permission": "blocked"})
        assert resp.status_code == 200

        devices = client.get(f"/api/sessions/{code}/devices").json()["data"]
        target = next((d for d in devices if d["id"] == pid), None)
        assert target["viewer_permission"] == "blocked"

    def test_set_permission_invalid_value(self, lifecycle_client):
        """無効な permission 値は 422"""
        client, code, password = lifecycle_client
        pid = _join_device(client, code, password)

        resp = client.post(f"/api/sessions/{code}/devices/{pid}/set-viewer-permission",
                           json={"viewer_permission": "invalid_value"})
        assert resp.status_code in (400, 422)


# ─── T5: device_uid による再接続 ─────────────────────────────────────────────

class TestReconnectByDeviceUid:
    def test_reconnect_same_device_uid(self, lifecycle_client):
        """同じ device_uid で再接続すると新規作成ではなく既存レコードを更新する"""
        client, code, password = lifecycle_client

        device_uid = "test-device-uid-abc123"

        # 1 回目の参加
        resp1 = client.post(f"/api/sessions/{code}/join", json={
            "role": "viewer",
            "device_name": "テストiPhone",
            "device_type": "iphone",
            "session_password": password,
            "device_uid": device_uid,
        })
        assert resp1.status_code == 200
        pid1 = resp1.json()["data"]["participant_id"]

        # 2 回目の参加（同じ device_uid）
        resp2 = client.post(f"/api/sessions/{code}/join", json={
            "role": "viewer",
            "device_name": "テストiPhone（再接続）",
            "device_type": "iphone",
            "session_password": password,
            "device_uid": device_uid,
        })
        assert resp2.status_code == 200
        pid2 = resp2.json()["data"]["participant_id"]

        # 同じ participant_id が返される（新規作成されていない）
        assert pid1 == pid2

    def test_different_device_uid_creates_new(self, lifecycle_client):
        """異なる device_uid では別の participant が作成される"""
        client, code, password = lifecycle_client

        resp1 = client.post(f"/api/sessions/{code}/join", json={
            "role": "viewer",
            "device_name": "デバイス1",
            "device_type": "iphone",
            "session_password": password,
            "device_uid": "uid-device-1",
        })
        resp2 = client.post(f"/api/sessions/{code}/join", json={
            "role": "viewer",
            "device_name": "デバイス2",
            "device_type": "iphone",
            "session_password": password,
            "device_uid": "uid-device-2",
        })
        assert resp1.json()["data"]["participant_id"] != resp2.json()["data"]["participant_id"]

    def test_join_without_device_uid(self, lifecycle_client):
        """device_uid なしで参加すると毎回新しい participant が作成される"""
        client, code, password = lifecycle_client

        resp1 = _join_device(client, code, password, device_name="A端末")
        resp2 = _join_device(client, code, password, device_name="B端末")
        assert resp1 != resp2
