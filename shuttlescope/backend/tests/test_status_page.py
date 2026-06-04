"""ステータス/メンテ API のテスト。公開読み取り + admin 書き込みゲート。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.utils.jwt_utils import create_access_token


def _admin():
    return {"Authorization": f"Bearer {create_access_token(user_id=1, role='admin', minutes=10)}"}


def test_public_status_is_anonymous_and_shaped():
    with TestClient(app) as client:
        r = client.get("/api/public/status")  # 認証なし
    assert r.status_code == 200
    b = r.json()
    assert "overall" in b and "active_incidents" in b and "maintenance" in b


def test_admin_incident_appears_then_resolves():
    with TestClient(app) as client:
        c = client.post("/api/status/incidents",
                        json={"title": "tunnel down", "severity": "critical", "component": "tunnel",
                              "reason": "cloudflared lost edge"},
                        headers=_admin())
        assert c.status_code == 201, c.text
        inc_id = c.json()["id"]
        # 公開ステータスに active として現れ、overall は down
        s = client.get("/api/public/status").json()
        assert any(i["id"] == inc_id for i in s["active_incidents"])
        assert s["overall"] == "down"
        # 解決 → active から消える
        p = client.patch(f"/api/status/incidents/{inc_id}", json={"resolved": True}, headers=_admin())
        assert p.status_code == 200 and p.json()["status"] == "resolved"
        s2 = client.get("/api/public/status").json()
        assert all(i["id"] != inc_id for i in s2["active_incidents"])


def test_non_admin_cannot_create_incident():
    with TestClient(app) as client:
        r = client.post("/api/status/incidents", json={"title": "x", "severity": "minor"},
                        headers={"Authorization": f"Bearer {create_access_token(user_id=5, role='coach', minutes=10)}"})
    assert r.status_code in (401, 403)


def test_maintenance_appears_in_public():
    with TestClient(app) as client:
        c = client.post("/api/status/maintenance",
                        json={"title": "メンテ", "body": "6/10 02:00 から 2h",
                              "scheduled_start": "2099-06-10T02:00:00"},
                        headers=_admin())
        assert c.status_code == 201, c.text
        mid = c.json()["id"]
        s = client.get("/api/public/status").json()
        assert any(m["id"] == mid for m in s["maintenance"])


def test_invalid_severity_422():
    with TestClient(app) as client:
        r = client.post("/api/status/incidents", json={"title": "x", "severity": "boom"}, headers=_admin())
    assert r.status_code == 422
