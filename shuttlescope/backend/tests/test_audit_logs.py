"""Phase B-5 audit log 閲覧エンドポイントのテスト。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


ADMIN_USER = "admin_al"
ADMIN_PASS = "AuditAdmin1!"


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


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={
        "grant_type": "credential", "identifier": username, "password": password,
    })
    assert r.status_code == 200, r.text
    return r.json()


class TestAuditLogList:
    def test_admin_can_list_and_filter(self, client):
        data = _login(client, ADMIN_USER, ADMIN_PASS)
        access = data["access_token"]

        # 失敗ログインを 1 件挟む（監査行が 1 件増えるはず）
        client.post("/api/auth/login", json={
            "grant_type": "credential", "identifier": ADMIN_USER, "password": "bogus",
        })

        resp = client.get(
            "/api/auth/audit-logs?limit=50",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200
        rows = resp.json()["data"]
        assert isinstance(rows, list)
        actions = [r["action"] for r in rows]
        assert "login" in actions
        assert "login_failed" in actions

        # action フィルタ
        only_failed = client.get(
            "/api/auth/audit-logs?action=login_failed",
            headers={"Authorization": f"Bearer {access}"},
        ).json()["data"]
        assert only_failed
        assert all(r["action"] == "login_failed" for r in only_failed)

    def test_non_admin_rejected(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        admin_access = admin["access_token"]
        # 別ユーザー作成
        resp = client.post(
            "/api/auth/users",
            json={"username": "analyst1", "role": "analyst",
                  "display_name": "A1", "password": "AnalystPass1!",
                  "team_name": "TestTeam"},
            headers={"Authorization": f"Bearer {admin_access}"},
        )
        assert resp.status_code in (200, 201)
        analyst = _login(client, "analyst1", "AnalystPass1!")
        forbidden = client.get(
            "/api/auth/audit-logs",
            headers={"Authorization": f"Bearer {analyst['access_token']}"},
        )
        assert forbidden.status_code == 403

    def test_unauthenticated_rejected(self, client):
        resp = client.get("/api/auth/audit-logs")
        assert resp.status_code in (401, 403)

    def test_limit_is_clamped(self, client):
        data = _login(client, ADMIN_USER, ADMIN_PASS)
        resp = client.get(
            "/api/auth/audit-logs?limit=99999",
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
        assert resp.status_code == 200

    def test_invalid_since_returns_422(self, client):
        data = _login(client, ADMIN_USER, ADMIN_PASS)
        resp = client.get(
            "/api/auth/audit-logs?since=not-a-date",
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
        assert resp.status_code == 422


class TestAuditLogHashChain:
    def test_chain_is_intact_after_logins(self, client, test_engine):
        # Round 258 R10 F-3 fix: account lockout が atomic CASE UPDATE で 3-attempt 制
        # になった結果、`ADMIN_USER` で 3 連続 bogus login を打つと admin 自身が lock
        # されて verify endpoint も 403 を返す。
        # 修正: 複数イベントを記録する目的なら **存在しない username** に向けて打てば
        # 誰の account も lock されない & chain には login_failed イベントが残る。
        data = _login(client, ADMIN_USER, ADMIN_PASS)
        access = data["access_token"]
        # 複数イベントを記録 (admin 自身を lock しないように nonexistent ユーザに対して)
        for _ in range(3):
            client.post("/api/auth/login", json={
                "grant_type": "credential", "identifier": "nonexistent_user_for_audit_chain",
                "password": "bogus",
            })

        resp = client.get(
            "/api/auth/audit-logs/verify",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["ok"] is True
        assert body["first_bad_id"] is None
        assert body["checked"] >= 3

    def test_tamper_is_detected(self, client, test_engine):
        data = _login(client, ADMIN_USER, ADMIN_PASS)
        access = data["access_token"]
        client.post("/api/auth/login", json={
            "grant_type": "credential", "identifier": ADMIN_USER, "password": "bogus",
        })

        # row を改ざんする（details を書き換え）
        from sqlalchemy.orm import sessionmaker
        from backend.db.models import AccessLog
        Session = sessionmaker(bind=test_engine)
        with Session() as s:
            row = s.query(AccessLog).order_by(AccessLog.id.asc()).first()
            assert row is not None
            row.details = '{"tampered": true}'
            s.commit()
            tampered_id = row.id

        resp = client.get(
            "/api/auth/audit-logs/verify",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["ok"] is False
        assert body["first_bad_id"] == tampered_id

    def test_non_admin_cannot_verify(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        client.post(
            "/api/auth/users",
            json={"username": "analyst_v", "role": "analyst",
                  "display_name": "AV", "password": "AnalystPass1!",
                  "team_name": "TestTeam"},
            headers={"Authorization": f"Bearer {admin['access_token']}"},
        )
        analyst = _login(client, "analyst_v", "AnalystPass1!")
        resp = client.get(
            "/api/auth/audit-logs/verify",
            headers={"Authorization": f"Bearer {analyst['access_token']}"},
        )
        assert resp.status_code == 403


def test_deleted_user_audit_rows_remain_orphaned_and_chain_intact(client, test_engine):
    """B-2: user deletion must not rewrite append-only audit rows.

    access_logs.user_id intentionally becomes an orphan integer reference after
    user deletion. Nulling/deleting it would change the canonical row bytes and
    break the HMAC chain. Audit API may no longer resolve a username, but the
    immutable actor identifier and chain must remain intact.
    """
    from sqlalchemy.orm import sessionmaker
    from backend.db.models import AccessLog, User
    from backend.routers.auth import _hash_password

    admin = _login(client, ADMIN_USER, ADMIN_PASS)
    admin_access = admin["access_token"]

    Session = sessionmaker(bind=test_engine)
    with Session() as db:
        target = User(
            username="audit_orphan_target",
            role="analyst",
            display_name="Audit Orphan Target",
            hashed_credential=_hash_password("AuditTarget1!"),
            is_test=True,
            awaiting_admin_approval=False,
            consent_required=False,
        )
        db.add(target)
        db.commit()
        target_id = target.id

    target_login = _login(client, "audit_orphan_target", "AuditTarget1!")
    assert target_login["role"] == "analyst"

    with Session() as db:
        before_ids = [
            row.id
            for row in db.query(AccessLog)
            .filter(AccessLog.user_id == target_id)
            .order_by(AccessLog.id.asc())
            .all()
        ]
        assert before_ids, "target login should have produced an audit row"

    deleted = client.delete(
        f"/api/auth/users/{target_id}",
        headers={"Authorization": f"Bearer {admin_access}"},
    )
    assert deleted.status_code == 200, deleted.text

    with Session() as db:
        assert db.get(User, target_id) is None
        after_rows = (
            db.query(AccessLog)
            .filter(AccessLog.user_id == target_id)
            .order_by(AccessLog.id.asc())
            .all()
        )
        assert [row.id for row in after_rows] == before_ids

    listed = client.get(
        f"/api/auth/audit-logs?user_id={target_id}&limit=50",
        headers={"Authorization": f"Bearer {admin_access}"},
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    assert rows
    assert all(row["user_id"] == target_id for row in rows)
    assert all(row["username"] is None for row in rows)

    verified = client.get(
        "/api/auth/audit-logs/verify",
        headers={"Authorization": f"Bearer {admin_access}"},
    )
    assert verified.status_code == 200, verified.text
    body = verified.json()["data"]
    assert body["ok"] is True
    assert body["first_bad_id"] is None
