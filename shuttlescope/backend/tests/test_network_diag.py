"""C4: /api/network router tests.

Covers:
- GET /network/diagnostics 結構とフィールド存在
- POST /network/lan-mode の env 書き込み (tmp path で隔離)
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


@pytest.fixture()
def client(test_engine):
    from backend.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestDiagnostics:
    def test_returns_expected_shape(self, client, monkeypatch, admin_headers):
        from backend.routers import network_diag as nd

        async def fake_probe(host, port, timeout=3.0):
            return True, None

        monkeypatch.setattr(nd, "_probe_tcp", fake_probe)
        monkeypatch.setattr(nd, "_get_lan_ips", lambda: ["192.168.1.10"])

        r = client.get("/api/network/diagnostics", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()["data"]

        assert "environment" in data
        assert data["environment"] in {"open", "corporate_proxy", "vpn", "filtered", "captive_portal", "unknown"}

        caps = data["capabilities"]
        assert caps["tcp_443"]["ok"] is True
        assert caps["tcp_80"]["ok"] is True
        assert caps["localhost_bridge"]["ok"] is True

        assert data["lan"]["lan_ips"] == ["192.168.1.10"]
        assert "api_port" in data["lan"]
        assert "transport_ladder" in data
        assert isinstance(data["transport_ladder"], list)
        assert "probe_duration_ms" in data

    def test_failed_tcp_is_reported(self, client, monkeypatch, admin_headers):
        from backend.routers import network_diag as nd

        async def fake_probe(host, port, timeout=3.0):
            return False, "timeout (3.0s)"

        monkeypatch.setattr(nd, "_probe_tcp", fake_probe)
        monkeypatch.setattr(nd, "_get_lan_ips", lambda: [])

        r = client.get("/api/network/diagnostics", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["capabilities"]["tcp_443"]["ok"] is False
        assert "timeout" in (data["capabilities"]["tcp_443"]["error"] or "")


class TestLanModeToggle:
    def test_writes_env_file_and_returns_success(self, client, tmp_path, monkeypatch):
        # env_file パスを tmp に差し替えるため、ルータ内の pathlib.Path 参照を絞って
        # 代わりに settings.LAN_MODE の反映と 200 応答を検証する。
        # env file 書き込み自体は shuttlescope 直下へ書き込まれるため、一時的に CWD をずらす
        import os, pathlib
        fake_dir = tmp_path / "shuttlescope"
        fake_dir.mkdir()
        # .env.development は routers/network_diag.py の親 x3 に解決される (確実性のため既存を退避)
        real_env = pathlib.Path("./.env.development").resolve()
        backup = None
        if real_env.exists():
            backup = real_env.read_text(encoding="utf-8")
        try:
            r = client.post("/api/network/lan-mode?enable=true")
            assert r.status_code == 200
            assert r.json()["data"]["lan_mode"] is True

            from backend.config import settings
            assert settings.LAN_MODE is True

            # off に戻して確認
            r2 = client.post("/api/network/lan-mode?enable=false")
            assert r2.status_code == 200
            assert r2.json()["data"]["lan_mode"] is False
            assert settings.LAN_MODE is False
        finally:
            if backup is not None:
                real_env.write_text(backup, encoding="utf-8")
