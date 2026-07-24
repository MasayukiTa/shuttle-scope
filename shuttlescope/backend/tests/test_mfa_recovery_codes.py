"""MFA リカバリコードのテスト。

背景 (障害): 2026-07 に w32time 停止でサーバ時計がずれ TOTP が一致せず、admin が
自分のアカウントから締め出された。当時リカバリ手段が無く、DB を直接書き換えて
totp_enabled を落とすしか復旧方法が無かった。本テストはその復旧経路が実際に
機能し、かつ悪用できないことを検証する。
"""
import time

from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import MfaRecoveryCode, User
from backend.main import app
from backend.routers.auth import (
    _RECOVERY_CODE_COUNT,
    _hash_recovery_code,
    _hotp_value,
    _hash_password,
    _normalize_recovery_code,
)
from backend.utils.jwt_utils import create_access_token


def _current_totp(secret: str) -> str:
    return f"{_hotp_value(secret, int(time.time()) // 30):06d}"


def _make_user(db_session, username: str = "mfa_user") -> User:
    db_session.query(User).filter(User.username == username).delete()
    db_session.commit()
    user = User(
        username=username,
        role="analyst",
        hashed_credential=_hash_password("correct-horse-battery"),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _auth_headers(user: User) -> dict:
    token = create_access_token(user.id, user.role)
    return {"Authorization": f"Bearer {token}"}


def _enroll_mfa(client: TestClient, user: User, db_session) -> list[str]:
    """setup → confirm まで通してリカバリコードを受け取る。"""
    headers = _auth_headers(user)
    resp = client.post("/api/auth/mfa/setup", headers=headers)
    assert resp.status_code == 200, resp.text
    secret = resp.json()["secret"]
    resp = client.post(
        "/api/auth/mfa/confirm", headers=headers, json={"code": _current_totp(secret)}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    return body["recovery_codes"]


def test_confirm_issues_recovery_codes(db_session):
    """MFA 有効化時にリカバリコードが発行され、DB には平文が残らない。"""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        user = _make_user(db_session)
        codes = _enroll_mfa(client, user, db_session)

        assert len(codes) == _RECOVERY_CODE_COUNT
        assert len(set(codes)) == _RECOVERY_CODE_COUNT, "コードが重複している"
        for code in codes:
            # 表示形式 XXXX-XXXX-XXXX-XXXX
            assert len(code) == 19 and code.count("-") == 3
            assert len(_normalize_recovery_code(code)) == 16

        rows = (
            db_session.query(MfaRecoveryCode)
            .filter(MfaRecoveryCode.user_id == user.id)
            .all()
        )
        assert len(rows) == _RECOVERY_CODE_COUNT
        stored = {r.code_hash for r in rows}
        # 平文が保存されていないこと
        assert not (stored & set(codes))
        # ハッシュが一致すること
        assert stored == {_hash_recovery_code(c) for c in codes}
        assert all(r.used_at is None for r in rows)
    finally:
        app.dependency_overrides.clear()


def test_login_with_recovery_code_succeeds_and_consumes_it(db_session):
    """本番障害の再現: TOTP が使えなくてもリカバリコードでログインでき、
    同じコードは二度と使えない。"""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        user = _make_user(db_session)
        codes = _enroll_mfa(client, user, db_session)

        resp = client.post(
            "/api/auth/login",
            json={
                "grant_type": "password",
                "username": user.username,
                "password": "correct-horse-battery",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["mfa_required"] is True
        mfa_token = resp.json()["mfa_token"]

        resp = client.post(
            "/api/auth/mfa/login",
            headers={"Authorization": f"Bearer {mfa_token}"},
            json={"mfa_token": mfa_token, "recovery_code": codes[0]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]

        # 消費済みになっている
        row = (
            db_session.query(MfaRecoveryCode)
            .filter(
                MfaRecoveryCode.user_id == user.id,
                MfaRecoveryCode.code_hash == _hash_recovery_code(codes[0]),
            )
            .one()
        )
        db_session.refresh(row)
        assert row.used_at is not None

        # 同じコードの再使用は拒否される (単回使用)
        resp = client.post(
            "/api/auth/login",
            json={
                "grant_type": "password",
                "username": user.username,
                "password": "correct-horse-battery",
            },
        )
        mfa_token2 = resp.json()["mfa_token"]
        resp = client.post(
            "/api/auth/mfa/login",
            headers={"Authorization": f"Bearer {mfa_token2}"},
            json={"mfa_token": mfa_token2, "recovery_code": codes[0]},
        )
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_recovery_code_accepts_formatting_variants(db_session):
    """区切り・大小文字の揺れを吸収する (紙から手打ちされる前提)。"""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        user = _make_user(db_session)
        codes = _enroll_mfa(client, user, db_session)
        messy = codes[0].replace("-", " ").lower()

        resp = client.post(
            "/api/auth/login",
            json={
                "grant_type": "password",
                "username": user.username,
                "password": "correct-horse-battery",
            },
        )
        mfa_token = resp.json()["mfa_token"]
        resp = client.post(
            "/api/auth/mfa/login",
            headers={"Authorization": f"Bearer {mfa_token}"},
            json={"mfa_token": mfa_token, "recovery_code": messy},
        )
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()


def test_wrong_recovery_code_is_rejected(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        user = _make_user(db_session)
        _enroll_mfa(client, user, db_session)

        resp = client.post(
            "/api/auth/login",
            json={
                "grant_type": "password",
                "username": user.username,
                "password": "correct-horse-battery",
            },
        )
        mfa_token = resp.json()["mfa_token"]
        resp = client.post(
            "/api/auth/mfa/login",
            headers={"Authorization": f"Bearer {mfa_token}"},
            json={"mfa_token": mfa_token, "recovery_code": "AAAA-BBBB-CCCC-DDDD"},
        )
        assert resp.status_code == 401
        # 未使用のまま (誤入力で在庫が減らない)
        unused = (
            db_session.query(MfaRecoveryCode)
            .filter(
                MfaRecoveryCode.user_id == user.id,
                MfaRecoveryCode.used_at.is_(None),
            )
            .count()
        )
        assert unused == _RECOVERY_CODE_COUNT
    finally:
        app.dependency_overrides.clear()


def test_cannot_send_both_code_and_recovery_code(db_session):
    """1 リクエストで 2 種類の試行をさせない (ブルートフォース計数の回避防止)。"""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        user = _make_user(db_session)
        codes = _enroll_mfa(client, user, db_session)

        resp = client.post(
            "/api/auth/login",
            json={
                "grant_type": "password",
                "username": user.username,
                "password": "correct-horse-battery",
            },
        )
        mfa_token = resp.json()["mfa_token"]
        resp = client.post(
            "/api/auth/mfa/login",
            headers={"Authorization": f"Bearer {mfa_token}"},
            json={"mfa_token": mfa_token, "code": "000000", "recovery_code": codes[0]},
        )
        assert resp.status_code == 422
        # どちらも指定しないのも拒否
        resp = client.post(
            "/api/auth/mfa/login",
            headers={"Authorization": f"Bearer {mfa_token}"},
            json={"mfa_token": mfa_token},
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_regenerate_invalidates_old_codes(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        user = _make_user(db_session)
        old_codes = _enroll_mfa(client, user, db_session)
        db_session.refresh(user)
        secret = user.totp_secret

        headers = _auth_headers(user)
        resp = client.post(
            "/api/auth/mfa/recovery/regenerate",
            headers=headers,
            json={"code": _current_totp(secret)},
        )
        assert resp.status_code == 200, resp.text
        new_codes = resp.json()["recovery_codes"]
        assert len(new_codes) == _RECOVERY_CODE_COUNT
        assert not (set(new_codes) & set(old_codes))

        # 旧コードは DB から消えている
        rows = (
            db_session.query(MfaRecoveryCode)
            .filter(MfaRecoveryCode.user_id == user.id)
            .all()
        )
        assert len(rows) == _RECOVERY_CODE_COUNT
        assert {r.code_hash for r in rows} == {_hash_recovery_code(c) for c in new_codes}

        # 旧コードでのログインは失敗する
        resp = client.post(
            "/api/auth/login",
            json={
                "grant_type": "password",
                "username": user.username,
                "password": "correct-horse-battery",
            },
        )
        mfa_token = resp.json()["mfa_token"]
        resp = client.post(
            "/api/auth/mfa/login",
            headers={"Authorization": f"Bearer {mfa_token}"},
            json={"mfa_token": mfa_token, "recovery_code": old_codes[0]},
        )
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_regenerate_requires_valid_totp(db_session):
    """access token を奪った攻撃者が勝手にコードを握れないこと。"""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        user = _make_user(db_session)
        _enroll_mfa(client, user, db_session)

        resp = client.post(
            "/api/auth/mfa/recovery/regenerate",
            headers=_auth_headers(user),
            json={"code": "000000"},
        )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_regenerate_rejects_mfa_pending_token(db_session):
    """パスワードだけを知る攻撃者 (mfa_pending トークン) は再発行できない。"""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        user = _make_user(db_session)
        _enroll_mfa(client, user, db_session)

        resp = client.post(
            "/api/auth/login",
            json={
                "grant_type": "password",
                "username": user.username,
                "password": "correct-horse-battery",
            },
        )
        mfa_token = resp.json()["mfa_token"]
        resp = client.post(
            "/api/auth/mfa/recovery/regenerate",
            headers={"Authorization": f"Bearer {mfa_token}"},
            json={"code": "000000"},
        )
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_disable_mfa_purges_recovery_codes(db_session):
    """MFA 無効化で旧コードが失効する (再有効化時に古い紙が通らない)。"""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        user = _make_user(db_session)
        _enroll_mfa(client, user, db_session)
        db_session.refresh(user)

        resp = client.post(
            "/api/auth/mfa/disable",
            headers=_auth_headers(user),
            json={"code": _current_totp(user.totp_secret)},
        )
        assert resp.status_code == 200, resp.text
        remaining = (
            db_session.query(MfaRecoveryCode)
            .filter(MfaRecoveryCode.user_id == user.id)
            .count()
        )
        assert remaining == 0
    finally:
        app.dependency_overrides.clear()


def test_status_reports_remaining_count(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        user = _make_user(db_session)
        codes = _enroll_mfa(client, user, db_session)

        resp = client.get("/api/auth/mfa/status", headers=_auth_headers(user))
        assert resp.status_code == 200
        assert resp.json()["recovery_codes_remaining"] == _RECOVERY_CODE_COUNT

        # 1 本消費すると残数が減る
        resp = client.post(
            "/api/auth/login",
            json={
                "grant_type": "password",
                "username": user.username,
                "password": "correct-horse-battery",
            },
        )
        mfa_token = resp.json()["mfa_token"]
        client.post(
            "/api/auth/mfa/login",
            headers={"Authorization": f"Bearer {mfa_token}"},
            json={"mfa_token": mfa_token, "recovery_code": codes[0]},
        )
        resp = client.get("/api/auth/mfa/status", headers=_auth_headers(user))
        assert resp.json()["recovery_codes_remaining"] == _RECOVERY_CODE_COUNT - 1
    finally:
        app.dependency_overrides.clear()
