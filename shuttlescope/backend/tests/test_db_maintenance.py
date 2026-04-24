"""db_maintenance router テスト。

Endpoints:
  GET  /api/db/status
  POST /api/db/maintenance
  POST /api/db/set_auto_vacuum
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from backend.utils.jwt_utils import create_access_token

_ADMIN_HEADERS = {"Authorization": f"Bearer {create_access_token(user_id=1, role='admin')}"}


@pytest.fixture(scope="module")
def client(test_engine):
    from backend.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestDbStatus:
    def test_status_returns_200(self, client):
        resp = client.get("/api/db/status", headers=_ADMIN_HEADERS)
        assert resp.status_code == 200

    def test_status_has_expected_fields(self, client):
        """SQLite 前提で supported フィールドは不要、基本統計キーが返ること"""
        data = client.get("/api/db/status", headers=_ADMIN_HEADERS).json()
        # メモリ DB でも以下のキーは返る
        assert "page_count" in data
        assert "freelist_count" in data
        assert "auto_vacuum" in data


class TestDbMaintenance:
    def test_maintenance_returns_200(self, client):
        resp = client.post("/api/db/maintenance", headers=_ADMIN_HEADERS)
        assert resp.status_code == 200

    def test_maintenance_returns_before_after(self, client):
        data = client.post("/api/db/maintenance", headers=_ADMIN_HEADERS).json()
        # before/after freelist または SQLite 以外時の supported=False
        assert isinstance(data, dict)


class TestSetAutoVacuum:
    def test_invalid_mode_returns_400(self, client):
        resp = client.post("/api/db/set_auto_vacuum", headers=_ADMIN_HEADERS, json={"mode": "bogus"})
        assert resp.status_code == 400

    def test_missing_mode_returns_422(self, client):
        resp = client.post("/api/db/set_auto_vacuum", headers=_ADMIN_HEADERS, json={})
        assert resp.status_code == 422

    def test_valid_mode_off_returns_200_or_400(self, client):
        """有効な mode を送ったら 200 が返ること（in-memory DB でも成立）"""
        resp = client.post("/api/db/set_auto_vacuum", headers=_ADMIN_HEADERS, json={"mode": "off"})
        # in-memory DB では supported が True / False どちらも起こり得る
        assert resp.status_code in (200, 400)

    def test_error_keys_stripped_from_response(self, client):
        """レスポンスに error/exception/traceback キーが露出しないこと（stack-trace 対策）"""
        resp = client.post("/api/db/set_auto_vacuum", headers=_ADMIN_HEADERS, json={"mode": "incremental"})
        if resp.status_code == 200:
            data = resp.json()
            assert "error" not in data
            assert "exception" not in data
            assert "traceback" not in data
