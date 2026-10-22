"""MFA 失効の 401 が文言ではなく安定コード (X-Error-Code) を返すことの回帰テスト (#659)。

frontend (LoginPage) は日本語の本文を部分一致で見るのをやめ、このヘッダで
「MFA トークン失効 → 初段ログインへ戻す」を判断する。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.routers.auth import MfaLoginRequest, mfa_login


def _request() -> Request:
    return Request({
        "type": "http",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    })


def test_invalid_mfa_token_returns_stable_error_code():
    req = MfaLoginRequest(mfa_token="not-a-jwt", code="000000")
    with pytest.raises(HTTPException) as ei:
        mfa_login(req, _request(), db=None)  # type: ignore[arg-type]
    assert ei.value.status_code == 401
    assert (ei.value.headers or {}).get("X-Error-Code") == "MFA_TOKEN_INVALID_OR_EXPIRED"
