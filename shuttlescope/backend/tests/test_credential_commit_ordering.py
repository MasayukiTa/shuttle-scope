"""認証情報の更新とトークン消費・失効の順序 (監査 #688 / #692 / #693)。

- #692 招待受諾: トークンの atomic claim をユーザ作成の commit より前に行い、
  claim に失敗したらユーザを作らない (single-use / 期限が認可 gate になる)。
- #693 パスワードリセット: 強度検証の失敗 (422) で一度きりのトークンを消費しない。
- #688 パスワード変更 / 管理者リセット / 公開リセット: セッション失効に失敗したら
  500 を返し、資格情報は変更されない (「失敗」と返しながら変更だけ確定、を作らない)。

パスワードやトークンの値はすべてテスト用のダミー。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.db import models as M
from backend.db.database import get_db
from backend.main import app, AdminWriteRateLimitMiddleware
from backend.routers import auth as auth_module
from backend.routers import auth_email
from backend.utils import jwt_utils
from backend.utils.email_token import (
    issue_invitation_token,
    issue_password_reset_token,
)

ADMIN_ID = 901
TARGET_ID = 902
OLD_PASSWORD = "Old-Passw0rd-Dummy!"
NEW_PASSWORD = "New-Passw0rd-Dummy!"
WEAK_PASSWORD = "abcdefghijkl"  # 8 文字以上だが文字種が 1 区分しかない


@pytest.fixture()
def api(db_session, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "ss_password_reset_enabled", 1, raising=False)
    auth_module._IP_LOGIN_TIMES.clear()
    AdminWriteRateLimitMiddleware._state.clear()
    auth_email._RATE_BUCKETS.clear()
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, raise_server_exceptions=False, client=("203.0.113.88", 50000))
    try:
        yield c
    finally:
        app.dependency_overrides.clear()
        AdminWriteRateLimitMiddleware._state.clear()
        auth_email._RATE_BUCKETS.clear()


def _mk_user(db, uid, role, username, password=None, email=None):
    u = M.User(
        id=uid,
        username=username,
        role=role,
        email=email,
        consent_required=False,
        hashed_credential=auth_module._hash_password(password) if password else None,
    )
    db.add(u)
    db.commit()
    return u


def _bearer(uid, role):
    return {"Authorization": "Bearer " + jwt_utils.create_access_token(user_id=uid, role=role)}


def _fail_revoke(monkeypatch):
    def _boom(user_id):
        raise RuntimeError("simulated revoke failure")

    monkeypatch.setattr(jwt_utils, "revoke_all_for_user", _boom)


def _credential(db, uid):
    db.expire_all()
    return db.get(M.User, uid).hashed_credential


# ── #692 招待受諾 ────────────────────────────────────────────────────────────
def _accept(api, token, username="inv_new_user"):
    return api.post("/api/auth/invitation/accept", json={
        "token": token,
        "username": username,
        "password": NEW_PASSWORD,
        "display_name": "Invited Dummy",
    })


def test_invitation_accept_creates_user_and_consumes_token_together(api, db_session):
    _mk_user(db_session, ADMIN_ID, "admin", "inviter_admin")
    token = issue_invitation_token(db_session, "inv@example.com", "coach", ADMIN_ID)
    r = _accept(api, token)
    assert r.status_code == 201, r.text
    user = db_session.query(M.User).filter_by(username="inv_new_user").one()
    rec = db_session.query(M.InvitationToken).one()
    assert rec.consumed_at is not None
    assert rec.consumed_by_user_id == user.id
    # 同じトークンの 2 回目は作成されない
    again = _accept(api, token, username="inv_second_user")
    assert again.status_code == 400
    assert db_session.query(M.User).filter_by(username="inv_second_user").first() is None


def test_invitation_claim_failure_after_peek_creates_no_user(api, db_session, monkeypatch):
    """peek の後・作成の前に別リクエストがトークンを消費した場合 (race)。"""
    _mk_user(db_session, ADMIN_ID, "admin", "inviter_admin")
    token = issue_invitation_token(db_session, "inv2@example.com", "coach", ADMIN_ID)
    real_peek = auth_email.peek_invitation_token

    def _peek_then_lose_the_race(db, tok):
        rec = real_peek(db, tok)
        db.query(M.InvitationToken).update({"consumed_at": datetime.utcnow()})
        db.commit()
        return rec

    monkeypatch.setattr(auth_email, "peek_invitation_token", _peek_then_lose_the_race)
    r = _accept(api, token)
    assert r.status_code == 400, r.text
    assert db_session.query(M.User).filter_by(username="inv_new_user").first() is None
    assert db_session.query(M.Player).count() == 0


def test_invitation_expiring_after_peek_creates_no_user(api, db_session, monkeypatch):
    _mk_user(db_session, ADMIN_ID, "admin", "inviter_admin")
    token = issue_invitation_token(db_session, "inv3@example.com", "player", ADMIN_ID)
    real_peek = auth_email.peek_invitation_token

    def _peek_then_expire(db, tok):
        rec = real_peek(db, tok)
        db.query(M.InvitationToken).update({"expires_at": datetime.utcnow() - timedelta(seconds=1)})
        db.commit()
        return rec

    monkeypatch.setattr(auth_email, "peek_invitation_token", _peek_then_expire)
    r = _accept(api, token)
    assert r.status_code == 400, r.text
    assert db_session.query(M.User).filter_by(username="inv_new_user").first() is None
    # player ロールの招待でも、取り消された作成の Player が残らない
    assert db_session.query(M.Player).count() == 0


# ── #693 リセットトークンを入力エラーで消費しない ──────────────────────────────
def _reset(api, token, password):
    return api.post("/api/auth/password/reset", json={"token": token, "new_password": password})


def test_weak_password_does_not_burn_the_reset_token(api, db_session):
    _mk_user(db_session, TARGET_ID, "coach", "reset_target", OLD_PASSWORD, "rt@example.com")
    token = issue_password_reset_token(db_session, TARGET_ID)
    before = _credential(db_session, TARGET_ID)

    weak = _reset(api, token, WEAK_PASSWORD)
    assert weak.status_code == 422, weak.text
    assert _credential(db_session, TARGET_ID) == before
    assert db_session.query(M.PasswordResetToken).one().consumed_at is None

    ok = _reset(api, token, NEW_PASSWORD)
    assert ok.status_code == 200, ok.text
    assert _credential(db_session, TARGET_ID) != before
    assert db_session.query(M.PasswordResetToken).one().consumed_at is not None
    # 使用済みトークンは再利用できない
    assert _reset(api, token, NEW_PASSWORD).status_code == 400


def test_invalid_reset_token_is_still_rejected(api, db_session):
    _mk_user(db_session, TARGET_ID, "coach", "reset_target", OLD_PASSWORD, "rt@example.com")
    assert _reset(api, "no-such-token-value", NEW_PASSWORD).status_code == 400


# ── #688 セッション失効に失敗したら資格情報を変えない ──────────────────────────
def test_public_reset_keeps_credential_and_token_when_revoke_fails(api, db_session, monkeypatch):
    _mk_user(db_session, TARGET_ID, "coach", "reset_target", OLD_PASSWORD, "rt@example.com")
    token = issue_password_reset_token(db_session, TARGET_ID)
    before = _credential(db_session, TARGET_ID)

    _fail_revoke(monkeypatch)
    r = _reset(api, token, NEW_PASSWORD)
    assert r.status_code == 500, r.text
    assert _credential(db_session, TARGET_ID) == before
    # トークンも使用済みにならない (障害が直れば同じリンクで続けられる)
    assert db_session.query(M.PasswordResetToken).one().consumed_at is None

    monkeypatch.undo()
    from backend.config import settings

    monkeypatch.setattr(settings, "ss_password_reset_enabled", 1, raising=False)
    ok = _reset(api, token, NEW_PASSWORD)
    assert ok.status_code == 200, ok.text
    assert _credential(db_session, TARGET_ID) != before


def test_change_password_keeps_credential_when_revoke_fails(api, db_session, monkeypatch):
    _mk_user(db_session, TARGET_ID, "coach", "pw_changer", OLD_PASSWORD, "pc@example.com")
    before = _credential(db_session, TARGET_ID)
    _fail_revoke(monkeypatch)
    r = api.post(
        "/api/auth/password",
        json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        headers=_bearer(TARGET_ID, "coach"),
    )
    assert r.status_code == 500, r.text
    assert _credential(db_session, TARGET_ID) == before


def test_change_password_success_still_changes_credential(api, db_session):
    _mk_user(db_session, TARGET_ID, "coach", "pw_changer", OLD_PASSWORD, "pc@example.com")
    before = _credential(db_session, TARGET_ID)
    r = api.post(
        "/api/auth/password",
        json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
        headers=_bearer(TARGET_ID, "coach"),
    )
    assert r.status_code == 200, r.text
    assert _credential(db_session, TARGET_ID) != before


def test_admin_reset_keeps_credential_when_revoke_fails(api, db_session, monkeypatch):
    _mk_user(db_session, ADMIN_ID, "admin", "reset_admin", OLD_PASSWORD)
    _mk_user(db_session, TARGET_ID, "coach", "reset_target", OLD_PASSWORD)
    before = _credential(db_session, TARGET_ID)
    _fail_revoke(monkeypatch)
    r = api.post(f"/api/auth/users/{TARGET_ID}/reset-password", headers=_bearer(ADMIN_ID, "admin"))
    assert r.status_code == 500, r.text
    assert "temporary_password" not in r.text
    # 一時パスワードを渡せなかったのに旧パスワードだけ無効、を作らない
    assert _credential(db_session, TARGET_ID) == before


def test_admin_reset_success_returns_a_working_temporary_password(api, db_session):
    _mk_user(db_session, ADMIN_ID, "admin", "reset_admin", OLD_PASSWORD)
    _mk_user(db_session, TARGET_ID, "coach", "reset_target", OLD_PASSWORD)
    before = _credential(db_session, TARGET_ID)
    r = api.post(f"/api/auth/users/{TARGET_ID}/reset-password", headers=_bearer(ADMIN_ID, "admin"))
    assert r.status_code == 200, r.text
    temp = r.json()["temporary_password"]
    db_session.expire_all()
    user = db_session.get(M.User, TARGET_ID)
    assert user.hashed_credential != before
    assert auth_module._verify_password(temp, user.hashed_credential)
