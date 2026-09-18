"""S-11: control-plane の admin JWT 判定が正規の認可を通ることのテスト。

`_is_admin_jwt` は `verify_token` の payload から `role == "admin"` を読むだけで、
`AuthCtx.is_admin` を通していなかった。is_admin は **MFA enrollment を DB で
確認**してから admin を名乗らせる設計なので、ここだけその検査を素通りしていた。

しかもこの述語を使う `require_local_operator_or_admin` は、control-plane の中で
**唯一 loopback を要求しない**経路で、クラスタ制御を通す。
他の全経路が拒否する token が、ここだけ通る状態だった。

`backend.main` を import しないので Python 3.10 でも走る。
"""
from __future__ import annotations

import pytest

import backend.utils.auth as auth_mod
import backend.utils.control_plane as cp
from backend.utils.auth import AuthCtx


class _Ctx:
    """`is_admin` だけを持つ認可コンテキストのスタブ。

    実物の `AuthCtx` を使わないのは、conftest の autouse fixture
    `_disable_admin_mfa_gate` が `ss_require_admin_mfa` を False にしており、
    その状態では `AuthCtx.is_admin` が role=admin なら常に True を返すため。
    ここで確かめたいのは MFA ゲートの挙動ではなく、
    **`_is_admin_jwt` が payload の role ではなく is_admin を見ているか**
    という一点なので、is_admin を直接与えて切り分ける。
    """

    def __init__(self, is_admin: bool):
        self.is_admin = is_admin


def _real_admin_token() -> str:
    """本物の署名済み admin JWT。

    偽の文字列だと `verify_token` が None を返すため、**旧実装でも False** に
    なってしまい、旧実装と新実装を区別できない (実際それで一度テストが
    「通ってしまった」)。payload の role が admin である本物を使うことで、
    旧実装なら True・新実装なら is_admin 次第、という差が出る。
    """
    from backend.utils.jwt_utils import create_access_token
    return create_access_token(1, "admin")


class _Req:
    """必要最小限の Request スタブ。"""

    def __init__(self, authorization: str | None = None, host: str = "203.0.113.9"):
        self.headers = {} if authorization is None else {"Authorization": authorization}
        self.client = type("C", (), {"host": host})()


def test_requires_a_bearer_header(monkeypatch):
    """Authorization が無ければ、get_auth の X-Role フォールバックに
    引きずられて True にならないこと。"""
    monkeypatch.setattr(
        auth_mod, "get_auth",
        lambda request: AuthCtx(role="admin", player_id=None, admin_mfa_ok=True),
    )
    assert cp._is_admin_jwt(_Req(authorization=None)) is False


def test_role_admin_but_is_admin_false_is_rejected(monkeypatch):
    """payload の role が admin でも、正規の認可が False なら通さない。

    旧実装は `payload["role"] == "admin"` だけを見ていたので、ここが True の
    まま通っていた。MFA 未 enrollment / 降格 / 削除済みユーザが該当する。
    """
    monkeypatch.setattr(auth_mod, "get_auth", lambda request: _Ctx(is_admin=False))
    assert cp._is_admin_jwt(_Req(f"Bearer {_real_admin_token()}")) is False


def test_admin_with_mfa_is_accepted(monkeypatch):
    monkeypatch.setattr(auth_mod, "get_auth", lambda request: _Ctx(is_admin=True))
    assert cp._is_admin_jwt(_Req(f"Bearer {_real_admin_token()}")) is True


def test_non_admin_role_is_rejected(monkeypatch):
    monkeypatch.setattr(
        auth_mod, "get_auth",
        lambda request: AuthCtx(role="coach", player_id=None, admin_mfa_ok=True),
    )
    assert cp._is_admin_jwt(_Req(f"Bearer {_real_admin_token()}")) is False


def test_failure_to_decide_denies(monkeypatch):
    """認可判定そのものが失敗したら拒否側へ倒すこと (fail closed)。"""
    def _boom(request):
        raise RuntimeError("auth backend down")
    monkeypatch.setattr(auth_mod, "get_auth", _boom)
    assert cp._is_admin_jwt(_Req(f"Bearer {_real_admin_token()}")) is False


def test_remote_request_without_admin_authorization_gets_403(monkeypatch):
    """gate 全体として、正規の認可が下りない token は遠隔から通らないこと。"""
    from fastapi import HTTPException

    monkeypatch.setattr(auth_mod, "get_auth", lambda request: _Ctx(is_admin=False))
    monkeypatch.setattr(cp, "is_loopback_request", lambda r: False)
    monkeypatch.setattr(cp, "is_trusted_cluster_request", lambda r: False)
    monkeypatch.setattr(cp, "_has_valid_operator_token", lambda r: False)
    with pytest.raises(HTTPException) as exc:
        cp.require_local_operator_or_admin(_Req(f"Bearer {_real_admin_token()}"))
    assert exc.value.status_code == 403
