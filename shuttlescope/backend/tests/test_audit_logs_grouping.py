"""監視画面向けの集約・除外・要約エンドポイントのテスト。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient


ADMIN_USER = "admin_alg"
ADMIN_PASS = "AuditGroup1!"


@pytest.fixture()
def client(test_engine, monkeypatch):
    from backend.routers import auth as _auth_module
    _auth_module._IP_LOGIN_TIMES.clear()
    from backend.db.models import User, RefreshToken, RevokedToken, AccessLog
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=test_engine)
    with Session() as s:
        s.query(AccessLog).delete()
        s.query(RefreshToken).delete()
        s.query(RevokedToken).delete()
        s.query(User).delete()
        s.commit()

    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", ADMIN_PASS)
    from backend.config import settings
    settings.BOOTSTRAP_ADMIN_USERNAME = ADMIN_USER
    settings.BOOTSTRAP_ADMIN_PASSWORD = ADMIN_PASS
    from backend.main import app
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as c:
        yield c


def _admin_headers(client) -> dict:
    r = client.post("/api/auth/login", json={
        "grant_type": "credential", "identifier": ADMIN_USER, "password": ADMIN_PASS,
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_security_groups_fold_one_scan_into_one_row(client, test_engine):
    from sqlalchemy.orm import sessionmaker
    from backend.db.models import SecurityEvent

    base = datetime(2026, 10, 1, 12, 0, 0)
    Session = sessionmaker(bind=test_engine)
    with Session() as db:
        db.query(SecurityEvent).delete()
        for i in range(40):
            db.add(SecurityEvent(
                event_type="probe_attempt", severity="warn", ip_addr="203.0.113.9",
                path=f"/probe{i}", ts=base + timedelta(seconds=i), details={},
            ))
        db.add(SecurityEvent(
            event_type="rate_limit_hit", severity="warn", ip_addr="203.0.113.10",
            path="/api/auth/login", ts=base, details={},
        ))
        db.add(SecurityEvent(event_type="llm_call", severity="info", details={}, ts=base))
        db.commit()

    headers = _admin_headers(client)
    res = client.get("/api/auth/audit-logs/security/groups", headers=headers)
    assert res.status_code == 200, res.text
    groups = res.json()["data"]
    assert {g["event_type"] for g in groups} == {"probe_attempt", "rate_limit_hit"}
    scan = next(g for g in groups if g["event_type"] == "probe_attempt")
    assert scan["count"] == 40
    assert scan["distinct_paths"] == 40
    assert len(scan["sample_paths"]) == 5


def test_groups_require_admin(client):
    for path in ("/api/auth/audit-logs/security/groups", "/api/auth/audit-logs/errors/groups"):
        assert client.get(path).status_code in (401, 403)


def test_error_groups_and_summary(client, test_engine):
    from sqlalchemy.orm import sessionmaker
    from backend.db.models import ErrorLog

    base = datetime(2026, 10, 1, 12, 0, 0)
    sql_message = (
        "(psycopg2.errors.ForeignKeyViolation) violates foreign key constraint \"users_team_id_fkey\"\n"
        "[SQL: UPDATE users SET team_id=%(team_id)s]\n"
        "[parameters: {'team_id': 9}]\n"
        "(Background on this error at: https://sqlalche.me/e/20/gkpj)"
    )
    Session = sessionmaker(bind=test_engine)
    with Session() as db:
        db.query(ErrorLog).delete()
        for i in range(3):
            db.add(ErrorLog(
                ts=base + timedelta(hours=i), method="GET", path="/api/db/status", status=500,
                exc_type="AttributeError", message="'Depends' object has no attribute 'get'",
                request_id=f"req{i}",
            ))
        db.add(ErrorLog(
            ts=base, method="POST", path="/api/users/4/approve", status=500,
            exc_type="IntegrityError", message=sql_message, request_id="reqsql",
        ))
        db.commit()

    headers = _admin_headers(client)
    groups = client.get("/api/auth/audit-logs/errors/groups", headers=headers).json()["data"]
    assert len(groups) == 2
    repeated = next(g for g in groups if g["exc_type"] == "AttributeError")
    assert repeated["count"] == 3
    assert repeated["last_request_id"] == "req2"

    rows = client.get("/api/auth/audit-logs/errors", headers=headers).json()["data"]
    sql_row = next(r for r in rows if r["exc_type"] == "IntegrityError")
    assert "[SQL:" not in sql_row["summary"]
    assert "sqlalche.me" not in sql_row["summary"]
    # 生の message は詳細表示用にそのまま残す
    assert "[SQL:" in sql_row["message"]


def test_request_list_hides_successful_monitoring_reads_by_default(client, test_engine):
    from sqlalchemy.orm import sessionmaker
    from backend.db.models import RequestLog

    Session = sessionmaker(bind=test_engine)
    with Session() as db:
        db.query(RequestLog).delete()
        for method, path, status in (
            ("GET", "/api/auth/audit-logs/security", 200),
            ("GET", "/api/auth/audit-logs/security", 403),
            ("GET", "/api/matches", 200),
        ):
            db.add(RequestLog(
                method=method, path=path, status=status, duration_ms=1, ip_addr="203.0.113.7",
            ))
        db.commit()

    headers = _admin_headers(client)
    url = "/api/auth/audit-logs/request?ip=203.0.113.7"
    seen = {(r["path"], r["status"]) for r in client.get(url, headers=headers).json()["data"]}
    assert seen == {("/api/auth/audit-logs/security", 403), ("/api/matches", 200)}

    all_rows = client.get(url + "&include_monitoring=true", headers=headers).json()["data"]
    assert len(all_rows) == 3
