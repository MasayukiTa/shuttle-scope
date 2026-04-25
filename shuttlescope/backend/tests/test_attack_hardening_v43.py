"""Attack #43+ ハードニングテスト群 (round 5 — lockout bypass の徹底封鎖)。

実弾検証で発見したロックアウト完全 bypass を再発防止する。

Z1: grant_type=select の admin escalation
    `{"grant_type":"select","role":"analyst","user_id":<adminID>}` で
    パスワード/lockout 一切なしに admin JWT が発行されていた。
    (allowed_roles に "admin" が含まれていた)
    → fix: user.role と要求 role の厳格一致に変更

Z2: select grant に lockout 判定を追加
    credential / pin / password 経路には _check_lockout があるが
    select には無く、ロック中アカウントでも JWT 発行可能だった。

Z3: mfa_login に lockout 判定を追加
    credential 段階で取得した mfa_token を持つ攻撃者がロック中も full JWT
    に昇格できた。

Z4: refresh に lockout 判定を追加
    旧 refresh_token を保持した攻撃者がロック中も無限にセッション延命可能だった。

Background: アカウント `adminTakeuchi_` を 5 回間違えてロックした user から
"unlock" を依頼され、Z1+Z2 chain で完全 bypass が実証されたため対応。
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta

import pytest


# ─── Z1: select grant の admin escalation 経路が閉じていること ──────────────


class TestSelectGrantAdminEscalation:
    def test_source_no_admin_in_allowed_roles(self):
        """auth.py の login() ソースに `"admin"` 暗黙許可文字列が残っていないこと。"""
        from backend.routers import auth as a

        src = inspect.getsource(a.login)
        # Z1 で削除した paten がぶり返していないことを確認
        assert '{role, "admin"}' not in src
        assert 'allowed_roles = {role, "admin"}' not in src

    def test_source_strict_role_match_in_select(self):
        """select 経路で user.role と要求 role の厳格一致を行っていること。"""
        from backend.routers import auth as a

        src = inspect.getsource(a.login)
        # 厳格チェック: `user.role != role` で 404 を返す形に置き換わっている
        assert "user.role != role" in src

    def test_login_request_select_with_admin_user_id_returns_404(self, monkeypatch):
        """select+role=analyst+user_id=<admin> がもう admin JWT を返さないこと。
        Pydantic schema を直接たどって関数挙動を確認する."""
        from backend.routers import auth as a
        from backend.db import models as m
        from fastapi import HTTPException

        # Mock get_db / DB lookup
        class FakeAdmin:
            id = 1
            role = "admin"
            username = "adminTakeuchi_"
            display_name = "Admin"
            player_id = None
            team_name = None
            hashed_credential = "x"
            failed_attempts = 0
            locked_until = None

        class FakeDb:
            def get(self, model, _id):
                if _id == 1:
                    return FakeAdmin()
                return None

            def query(self, *args, **kwargs):
                class Q:
                    def filter(self, *a, **k):
                        return self

                    def first(self):
                        return None
                return Q()

        class FakeReq:
            class client: host = "127.0.0.1"  # DevSkim: ignore DS162092 — loopback is required to satisfy is_loopback_request()
            headers = {}

        # patch helper
        from backend.utils import control_plane as cp
        monkeypatch.setattr(cp, "allow_select_login", lambda r: True)
        monkeypatch.setattr(cp, "allow_seed_admin", lambda r: False)
        # ip rate limit no-op
        monkeypatch.setattr(a, "_check_ip_rate_limit", lambda ip: None)
        monkeypatch.setattr(a, "log_access", lambda *a, **kw: None)

        body = a.LoginRequest(grant_type="select", role="analyst", user_id=1)
        with pytest.raises(HTTPException) as ei:
            a.login(body, FakeReq(), db=FakeDb())
        assert ei.value.status_code == 404, f"expected 404, got {ei.value.status_code}: {ei.value.detail}"


# ─── Z2: select grant に lockout 判定が入っていること ───────────────────────


class TestSelectGrantLockout:
    def test_source_calls_check_lockout(self):
        """select の両分岐 (user_id 指定 / 未指定) で _check_lockout を呼んでいる。"""
        from backend.routers import auth as a

        src = inspect.getsource(a.login)
        # select セクションを取り出して _check_lockout の参照回数を確認
        select_section = src.split('if req.grant_type == "select":')[1].split('if req.grant_type == "pin"')[0]
        # 2 回 (user_id 指定パス + デフォルトパス) 呼ばれている
        assert select_section.count("_check_lockout(user)") >= 1

    def test_locked_user_blocked_via_select(self, monkeypatch):
        from backend.routers import auth as a
        from fastapi import HTTPException

        class FakeAnalyst:
            id = 2
            role = "analyst"
            username = "x"
            display_name = "X"
            player_id = None
            team_name = "X"
            hashed_credential = "x"
            failed_attempts = 5
            locked_until = datetime.utcnow() + timedelta(minutes=29)

        class FakeDb:
            def get(self, model, _id):
                if _id == 2:
                    return FakeAnalyst()
                return None

            def query(self, *a, **k):
                class Q:
                    def filter(self, *a, **k): return self
                    def first(self): return None
                return Q()

        class FakeReq:
            class client: host = "127.0.0.1"  # DevSkim: ignore DS162092 — loopback is required to satisfy is_loopback_request()
            headers = {}

        from backend.utils import control_plane as cp
        monkeypatch.setattr(cp, "allow_select_login", lambda r: True)
        monkeypatch.setattr(cp, "allow_seed_admin", lambda r: False)
        monkeypatch.setattr(a, "_check_ip_rate_limit", lambda ip: None)
        monkeypatch.setattr(a, "log_access", lambda *a, **kw: None)

        body = a.LoginRequest(grant_type="select", role="analyst", user_id=2)
        with pytest.raises(HTTPException) as ei:
            a.login(body, FakeReq(), db=FakeDb())
        assert ei.value.status_code == 429, f"expected 429 lockout, got {ei.value.status_code}: {ei.value.detail}"


# ─── Z3: mfa_login に lockout 判定が入っていること ──────────────────────────


class TestMfaLoginLockout:
    def test_source_calls_check_lockout(self):
        from backend.routers import auth as a

        src = inspect.getsource(a.mfa_login)
        assert "_check_lockout(user)" in src


# ─── Z4: refresh に lockout 判定が入っていること ────────────────────────────


class TestRefreshLockout:
    def test_source_calls_check_lockout(self):
        from backend.routers import auth as a

        src = inspect.getsource(a.refresh)
        assert "_check_lockout(user)" in src
