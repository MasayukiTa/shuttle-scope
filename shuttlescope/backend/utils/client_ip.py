"""Round 258 R3 P0/P1 fix (VULN-3): trusted client IP resolver.

旧来は各 router が独自に `request.headers.get("CF-Connecting-IP")` を読み、
その IP をレート制限 / lockout / 監査ログ / Turnstile に使っていた。

CF-Connecting-IP / X-Forwarded-For / X-Real-IP は client が任意に送れる
ヘッダなので、リクエストが本当に Cloudflare 経由 (= localhost で稼働する
cloudflared プロセス) から来たときのみ信頼する。それ以外 (LAN 直接接続 /
SSRF / 設定ミス) では request.client.host を使う。

判定ルール:
  - request.client.host が loopback ("127.0.0.1" / "::1") のとき、
    CF-Connecting-IP > X-Real-IP > X-Forwarded-For (最初の値) を採用
  - それ以外は request.client.host をそのまま採用
  - CF-Connecting-IP が IPv4/IPv6 として無効なら無視

これにより、Cloudflare bypass で直接 backend に届いた偽 CF-Connecting-IP
ヘッダを信用しなくなる。
"""
from __future__ import annotations

import ipaddress
from typing import Optional

try:
    from starlette.requests import Request as _Req
    from starlette.websockets import WebSocket as _WS
except Exception:  # pragma: no cover
    _Req = object  # type: ignore
    _WS = object  # type: ignore


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _is_valid_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except (ValueError, TypeError):
        return False


def _direct_client_host(req) -> Optional[str]:
    try:
        return req.client.host if req.client else None
    except Exception:
        return None


def _direct_loopback(req) -> bool:
    h = _direct_client_host(req)
    return h in _LOOPBACK_HOSTS if h else False


def trusted_client_ip(request, default: str = "unknown") -> str:
    """Request の真のクライアント IP を返す。

    Loopback connection (cloudflared / Electron / dev) の場合のみ
    proxy ヘッダを信用する。それ以外は scope.client.host を返す。
    """
    if not _direct_loopback(request):
        return _direct_client_host(request) or default

    # Loopback 経由 = cloudflared / dev — proxy ヘッダを優先
    headers = getattr(request, "headers", {})
    for h in ("cf-connecting-ip", "x-real-ip"):
        v = (headers.get(h) or "").strip()
        if v and _is_valid_ip(v):
            return v
    xff = (headers.get("x-forwarded-for") or "").strip()
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first and _is_valid_ip(first):
            return first
    # フォールバック: 真の client = loopback 自体
    return _direct_client_host(request) or default
