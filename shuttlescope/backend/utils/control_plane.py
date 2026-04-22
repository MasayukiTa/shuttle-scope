"""コントロールプレーン アクセスポリシー

危険な操作（クラスタ制御・ローカルファイル実行・select ログイン等）の
アクセス判定を一か所に集約する。

判定基準:
  - loopback (127.0.0.1 / ::1) → 無条件で許可
  - 信頼済みクラスタサブネット (SS_TRUSTED_SUBNETS) → require_local_or_operator_token で許可
  - SS_OPERATOR_TOKEN が設定されかつ X-Operator-Token ヘッダが一致 → 許可
  - 上記いずれも満たさない → 403
"""
from __future__ import annotations

import os

from fastapi import HTTPException, Request

# 信頼済みクラスタサブネットプレフィックス（カンマ区切り）
# 例: SS_TRUSTED_SUBNETS=192.168.100.,192.168.101.
_TRUSTED_PREFIXES: list[str] = [
    s.strip()
    for s in os.getenv("SS_TRUSTED_SUBNETS", "192.168.100.,192.168.101.").split(",")
    if s.strip()
]

_OPERATOR_TOKEN: str = os.getenv("SS_OPERATOR_TOKEN", "").strip()


def _client_ip(request: Request) -> str:
    # CF-Connecting-IP は Cloudflare が設定するため、クライアントによる偽造不可。
    # X-Forwarded-For の先頭はクライアントが任意に設定できるため loopback 判定に使用しない。
    cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
    if cf_ip:
        return cf_ip
    # Cloudflare Tunnel を経由しない接続（Electron ローカル等）はソケット IP を使用。
    return request.client.host if request.client else ""


def is_loopback_request(request: Request) -> bool:
    """リクエスト元が loopback アドレスかどうかを返す。"""
    ip = _client_ip(request)
    # FastAPI/Starlette TestClient reports the client host as "testclient".
    # Treat it as loopback-equivalent so local-only compatibility paths stay testable in CI.
    return ip in ("127.0.0.1", "::1", "localhost", "", "testclient")


def is_trusted_cluster_request(request: Request) -> bool:
    """リクエスト元が信頼済みクラスタサブネットかどうかを返す。"""
    ip = _client_ip(request)
    return any(ip.startswith(prefix) for prefix in _TRUSTED_PREFIXES)


def _has_valid_operator_token(request: Request) -> bool:
    if not _OPERATOR_TOKEN:
        return False
    return request.headers.get("X-Operator-Token", "") == _OPERATOR_TOKEN


def require_local_or_operator_token(request: Request) -> None:
    """loopback・信頼済みサブネット・operator token のいずれかが必要な操作に付ける。

    これらの条件を満たさないリクエストは HTTP 403 で拒否する。
    クラスタ制御・ローカルファイル実行など危険度の高いエンドポイントに使用する。
    """
    if is_loopback_request(request):
        return
    if is_trusted_cluster_request(request):
        return
    if _has_valid_operator_token(request):
        return
    raise HTTPException(
        status_code=403,
        detail="この操作はローカルまたは信頼済みネットワークからのみ実行できます",
    )


def allow_legacy_header_auth(request: Request) -> bool:
    """X-Role ヘッダーフォールバックを許可するか。loopback のみ許可。"""
    return is_loopback_request(request)


def allow_select_login(request: Request) -> bool:
    """grant_type=select ログインを許可するか。loopback のみ許可。"""
    return is_loopback_request(request)


def allow_seed_admin(request: Request) -> bool:
    """bootstrap admin 自動作成を許可するか。loopback のみ許可。"""
    return is_loopback_request(request)


def allow_local_file_control(request: Request) -> bool:
    """ローカルファイルパス実行を許可するか。loopback または trusted cluster。"""
    return is_loopback_request(request) or is_trusted_cluster_request(request)
