"""C3: /api/settings router tests.

Covers:
- GET /api/settings returns defaults + auto-generates sync_device_id
- PUT /api/settings partial update (requires analyst)
- PUT without analyst auth is 403
- GET /api/settings/devices returns expected keys
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from backend.utils.jwt_utils import create_access_token

# Module-level constant replaced by lazy fixture (CI 403 fix)
@pytest.fixture()
def admin_headers():
    """Per-test fresh admin token (lazy fixture pattern, see test_db_maintenance.py)."""
    return {"Authorization": f"Bearer {create_access_token(user_id=1, role='admin')}"}


ADMIN_USER = "admin_settings"
ADMIN_PASS = "SettingsTest1!"


@pytest.fixture()
def client(test_engine, monkeypatch):
    from backend.routers import auth as _auth_module
    _auth_module._IP_LOGIN_TIMES.clear()
    from backend.db.models import User, RefreshToken, RevokedToken, AccessLog
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=test_engine)
    with Session() as s:
        s.query(AccessLog).delete()
        s.query(RefreshToken).delete()
        s.query(RevokedToken).delete()
        s.query(User).delete()
        # settings KV のクリア (CREATE TABLE IF NOT EXISTS で存在)
        try:
            s.execute(text("DELETE FROM app_settings"))
        except Exception:
            pass
        s.commit()

    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", ADMIN_PASS)
    from backend.config import settings
    settings.BOOTSTRAP_ADMIN_USERNAME = ADMIN_USER
    settings.BOOTSTRAP_ADMIN_PASSWORD = ADMIN_PASS
    from backend.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _login(client, username: str, password: str) -> str:
    r = client.post("/api/auth/login", json={
        "grant_type": "credential", "identifier": username, "password": password,
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class TestGetSettings:
    def test_returns_defaults_and_autogenerates_device_id(self, client):
        r = client.get("/api/settings")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["tracknet_enabled"] is True
        assert data["yolo_enabled"] is True
        # sync_device_id は自動生成されるので非空
        assert data["sync_device_id"]

    def test_device_id_persists_across_calls(self, client):
        r1 = client.get("/api/settings").json()["data"]["sync_device_id"]
        r2 = client.get("/api/settings").json()["data"]["sync_device_id"]
        assert r1 == r2


class TestPutSettings:
    def test_analyst_can_update_partial(self, client):
        access = _login(client, ADMIN_USER, ADMIN_PASS)
        r = client.put(
            "/api/settings",
            json={"settings": {"tracknet_enabled": False, "yolo_realtime_fps": 15}},
            headers={"Authorization": f"Bearer {access}"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["tracknet_enabled"] is False
        assert data["yolo_realtime_fps"] == 15

        # 他キーはデフォルト維持
        assert data["yolo_enabled"] is True

    def test_update_persists(self, client):
        access = _login(client, ADMIN_USER, ADMIN_PASS)
        client.put(
            "/api/settings",
            json={"settings": {"tracknet_backend": "cuda"}},
            headers={"Authorization": f"Bearer {access}"},
        )
        later = client.get("/api/settings").json()["data"]
        assert later["tracknet_backend"] == "cuda"

    def test_unauthenticated_rejected(self, client):
        r = client.put("/api/settings", json={"settings": {"tracknet_enabled": False}})
        assert r.status_code in (401, 403)


class TestGetDevices:
    def test_returns_expected_keys(self, client, admin_headers):
        r = client.get("/api/settings/devices", headers=admin_headers)
        assert r.status_code == 200
        j = r.json()
        assert j["success"] is True
        for key in ("cuda_devices", "openvino_devices", "onnx_providers"):
            assert key in j
            assert isinstance(j[key], list)
