"""管理操作の監査ログに「誰がやったか」(user_id) が残ること。

対象: 管理者によるパスワード再発行 / ユーザ削除 / 選手削除。
以前は reset-password と user 削除の監査行に user_id が入らず、実行者が追えなかった。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

ADMIN_USER = "admin_actor"
ADMIN_PASS = "AdminPass1234!"


@pytest.fixture()
def client(test_engine, monkeypatch):
    from backend.routers import auth as _auth_module
    _auth_module._IP_LOGIN_TIMES.clear()
    from backend.db.models import User, RefreshToken, RevokedToken, AccessLog
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=test_engine)
    with Session() as s:
        s.query(RefreshToken).delete()
        s.query(RevokedToken).delete()
        s.query(AccessLog).delete()
        s.query(User).delete()
        s.commit()

    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", ADMIN_PASS)
    from backend.config import settings
    settings.BOOTSTRAP_ADMIN_USERNAME = ADMIN_USER
    settings.BOOTSTRAP_ADMIN_PASSWORD = ADMIN_PASS
    from backend.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _login_admin(client) -> tuple[dict, int]:
    resp = client.post(
        "/api/auth/login",
        json={"grant_type": "credential", "identifier": ADMIN_USER, "password": ADMIN_PASS},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user_id"]


def _create_target(client, headers) -> int:
    resp = client.post(
        "/api/auth/users",
        json={
            "username": "target_actor",
            "role": "analyst",
            "display_name": "Target",
            "password": "TargetPass1!",
            "team_name": "TestTeam",
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["data"]["id"]


def _rows(test_engine, action: str):
    from backend.db.models import AccessLog
    from sqlalchemy.orm import sessionmaker
    with sessionmaker(bind=test_engine)() as s:
        return [
            (r.user_id, r.resource_type, r.resource_id, json.loads(r.details or "{}"), r.details or "")
            for r in s.query(AccessLog).filter(AccessLog.action == action).order_by(AccessLog.id.asc()).all()
        ]


def test_admin_reset_password_records_actor(client, test_engine):
    headers, admin_id = _login_admin(client)
    target_id = _create_target(client, headers)
    resp = client.post(f"/api/auth/users/{target_id}/reset-password", headers=headers)
    assert resp.status_code == 200, resp.text
    temp = resp.json()["temporary_password"]

    rows = _rows(test_engine, "password_reset_by_admin")
    assert len(rows) == 1
    user_id, rtype, rid, details, raw = rows[0]
    assert user_id == admin_id
    assert (rtype, rid) == ("user", target_id)
    assert details["target_user_id"] == target_id
    # 秘密値は監査ログに入れない
    assert temp not in raw


def test_user_delete_records_actor(client, test_engine):
    headers, admin_id = _login_admin(client)
    target_id = _create_target(client, headers)
    resp = client.delete(f"/api/auth/users/{target_id}", headers=headers)
    assert resp.status_code == 200, resp.text

    rows = _rows(test_engine, "user_deleted")
    assert len(rows) == 1
    user_id, rtype, rid, details, _raw = rows[0]
    assert user_id == admin_id
    assert (rtype, rid) == ("user", target_id)
    assert details["deleted_user_id"] == target_id


def test_player_delete_records_actor(client, test_engine):
    headers, admin_id = _login_admin(client)
    created = client.post("/api/players", json={"name": "Audit Target"}, headers=headers)
    assert created.status_code == 201, created.text
    player_id = created.json()["data"]["id"]
    resp = client.delete(f"/api/players/{player_id}", headers=headers)
    assert resp.status_code == 200, resp.text

    rows = _rows(test_engine, "player_deleted")
    assert len(rows) == 1
    user_id, rtype, rid, details, raw = rows[0]
    assert user_id == admin_id
    assert (rtype, rid) == ("player", player_id)
    assert details["deleted_player_id"] == player_id
    # 選手名などの個人データは残さない
    assert "Audit Target" not in raw


def test_audit_hash_chain_stays_valid_after_admin_actions(client, test_engine):
    from backend.utils.access_log import verify_chain
    from sqlalchemy.orm import sessionmaker
    headers, _admin_id = _login_admin(client)
    target_id = _create_target(client, headers)
    assert client.post(f"/api/auth/users/{target_id}/reset-password", headers=headers).status_code == 200
    with sessionmaker(bind=test_engine)() as s:
        result = verify_chain(s)
    assert result["ok"], result
