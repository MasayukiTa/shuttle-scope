"""LAN セッション認証・デバイス制御 API テスト

migration 0003 で追加された機能:
- SharedSession.password_hash  : セッションパスワード認証
- SessionParticipant 拡張フィールド: device_type / connection_role / connection_state など
- デバイス管理 API: /sessions/{code}/devices, activate-camera, deactivate-camera, set-role
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
def lan_client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def lan_client_with_session(db_session):
    """セッション作成済みクライアント"""
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    match = _make_match(db_session)
    db_session.commit()

    resp = client.post("/api/sessions", json={"match_id": match.id})
    assert resp.status_code == 201
    data = resp.json()["data"]

    yield client, data["session_code"], data.get("session_password"), match.id
    app.dependency_overrides.clear()


# ─── T1: セッション作成でパスワードが返される ────────────────────────────────

class TestSessionCreation:
    def test_session_created_with_password(self, lan_client, db_session):
        """POST /sessions でパスワードが平文で返される"""
        match = _make_match(db_session)
        db_session.commit()

        resp = lan_client.post("/api/sessions", json={"match_id": match.id})
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "session_password" in data
        assert len(data["session_password"]) >= 8
        assert data["has_password"] is True

    def test_session_has_camera_sender_url(self, lan_client, db_session):
        """作成セッションに camera_sender_urls が含まれる"""
        match = _make_match(db_session)
        db_session.commit()

        resp = lan_client.post("/api/sessions", json={"match_id": match.id})
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert "camera_sender_urls" in data

    def test_existing_session_reuse_no_password(self, lan_client, db_session):
        """既存セッションを再利用する場合はパスワードが返されない"""
        match = _make_match(db_session)
        db_session.commit()

        # 1回目: セッション作成
        resp1 = lan_client.post("/api/sessions", json={"match_id": match.id})
        assert resp1.status_code == 201

        # 2回目: 既存セッション再利用
        resp2 = lan_client.post("/api/sessions", json={"match_id": match.id})
        assert resp2.status_code == 201
        # 再利用時は session_password が含まれない（セキュリティ）
        data2 = resp2.json()["data"]
        assert "session_password" not in data2


# ─── T2: パスワード検証 ───────────────────────────────────────────────────────

class TestPasswordVerification:
    def test_join_valid_password(self, lan_client_with_session):
        """正しいパスワードで参加できる"""
        client, code, password, _ = lan_client_with_session
        resp = client.post(f"/api/sessions/{code}/join", json={
            "role": "coach",
            "device_name": "テストデバイス",
            "device_type": "iphone",
            "session_password": password,
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["participant_id"] is not None
        assert data["connection_role"] == "viewer"

    def test_join_invalid_password(self, lan_client_with_session):
        """誤パスワードで 401"""
        client, code, _, _ = lan_client_with_session
        resp = client.post(f"/api/sessions/{code}/join", json={
            "role": "coach",
            "device_name": "テストデバイス",
            "session_password": "wrongpassword",
        })
        assert resp.status_code == 401

    def test_join_missing_password_when_required(self, lan_client_with_session):
        """パスワード必須セッションでパスワードなしは 401"""
        client, code, _, _ = lan_client_with_session
        resp = client.post(f"/api/sessions/{code}/join", json={
            "role": "coach",
        })
        assert resp.status_code == 401

    def test_join_no_password_required_when_not_set(self, lan_client, db_session):
        """パスワード未設定セッションはパスワードなしで参加可能"""
        match = _make_match(db_session)
        db_session.commit()

        # パスワードなしでセッションを直接作成
        session = SharedSession(
            match_id=match.id,
            session_code="NOPASS",
            created_by_role="analyst",
        )
        db_session.add(session)
        db_session.commit()

        resp = lan_client.post("/api/sessions/NOPASS/join", json={"role": "viewer"})
        assert resp.status_code == 200


# ─── T3: デバイス管理 API ─────────────────────────────────────────────────────

class TestDeviceManagement:
    def _join(self, client, code, password, device_name="デバイス", device_type="iphone"):
        resp = client.post(f"/api/sessions/{code}/join", json={
            "role": "viewer",
            "device_name": device_name,
            "device_type": device_type,
            "session_password": password,
        })
        assert resp.status_code == 200
        return resp.json()["data"]["participant_id"]

    def test_device_list(self, lan_client_with_session):
        """GET /sessions/{code}/devices でデバイス一覧が返る"""
        client, code, password, _ = lan_client_with_session
        self._join(client, code, password, "iPhone1")
        self._join(client, code, password, "iPhone2")

        resp = client.get(f"/api/sessions/{code}/devices")
        assert resp.status_code == 200
        devices = resp.json()["data"]
        assert len(devices) == 2
        assert all("connection_role" in d for d in devices)
        assert all("connection_state" in d for d in devices)

    def test_activate_camera(self, lan_client_with_session):
        """デバイスをアクティブカメラに昇格できる"""
        client, code, password, _ = lan_client_with_session
        pid = self._join(client, code, password, "カメラ端末")

        resp = client.post(f"/api/sessions/{code}/devices/{pid}/activate-camera")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["connection_role"] == "active_camera"
        assert data["connection_state"] == "sending_video"

    def test_up_to_four_active_cameras_allowed(self, lan_client_with_session):
        """active_camera は最大4台まで同時許可される"""
        client, code, password, _ = lan_client_with_session
        pid1 = self._join(client, code, password, "端末1")
        pid2 = self._join(client, code, password, "端末2")
        pid3 = self._join(client, code, password, "端末3")
        pid4 = self._join(client, code, password, "端末4")

        client.post(f"/api/sessions/{code}/devices/{pid1}/activate-camera")
        client.post(f"/api/sessions/{code}/devices/{pid2}/activate-camera")
        client.post(f"/api/sessions/{code}/devices/{pid3}/activate-camera")
        client.post(f"/api/sessions/{code}/devices/{pid4}/activate-camera")

        devices_resp = client.get(f"/api/sessions/{code}/devices")
        devices = {d["id"]: d for d in devices_resp.json()["data"]}

        assert devices[pid1]["connection_role"] == "active_camera"
        assert devices[pid2]["connection_role"] == "active_camera"
        assert devices[pid3]["connection_role"] == "active_camera"
        assert devices[pid4]["connection_role"] == "active_camera"

    def test_fifth_active_camera_rejected(self, lan_client_with_session):
        """5台目の active_camera は 409 で拒否される"""
        client, code, password, _ = lan_client_with_session
        pids = [self._join(client, code, password, f"端末{i}") for i in range(1, 6)]

        for pid in pids[:4]:
            resp = client.post(f"/api/sessions/{code}/devices/{pid}/activate-camera")
            assert resp.status_code == 200

        resp = client.post(f"/api/sessions/{code}/devices/{pids[4]}/activate-camera")
        assert resp.status_code == 409

    def test_deactivate_camera(self, lan_client_with_session):
        """カメラを camera_candidate に降格できる"""
        client, code, password, _ = lan_client_with_session
        pid = self._join(client, code, password, "カメラ端末")

        client.post(f"/api/sessions/{code}/devices/{pid}/activate-camera")
        resp = client.post(f"/api/sessions/{code}/devices/{pid}/deactivate-camera")
        assert resp.status_code == 200
        assert resp.json()["data"]["connection_role"] == "camera_candidate"

    def test_set_role(self, lan_client_with_session):
        """connection_role を変更できる"""
        client, code, password, _ = lan_client_with_session
        pid = self._join(client, code, password, "コーチ端末", device_type="ipad")

        resp = client.post(f"/api/sessions/{code}/devices/{pid}/set-role", json={
            "connection_role": "camera_candidate",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["connection_role"] == "camera_candidate"


# ─── T4: パスワード再生成 ────────────────────────────────────────────────────

class TestRegeneratePassword:
    def test_regenerate_password(self, lan_client_with_session):
        """パスワード再生成で新しい平文パスワードが返される"""
        client, code, old_password, _ = lan_client_with_session

        resp = client.post(f"/api/sessions/{code}/regenerate-password")
        assert resp.status_code == 200
        new_password = resp.json()["data"]["session_password"]
        assert new_password != old_password
        assert len(new_password) >= 8

    def test_old_password_rejected_after_regenerate(self, lan_client_with_session):
        """再生成後に古いパスワードは使えない"""
        client, code, old_password, _ = lan_client_with_session

        client.post(f"/api/sessions/{code}/regenerate-password")

        resp = client.post(f"/api/sessions/{code}/join", json={
            "role": "viewer",
            "session_password": old_password,
        })
        assert resp.status_code == 401
