"""コントロールプレーン アクセスポリシー

危険な操作（クラスタ制御・ローカルファイル実行・select ログイン等）の
アクセス判定を一か所に集約する。

判定基準:
  - loopback (127.0.0.1 / ::1) → 無条件で許可
  - 信頼済みクラスタサブネット (SS_TRUSTED_SUBNETS) → require_local_or_operator_token で許可
  - SS_OPERATOR_TOKEN が設定されかつ X-Operator-Token ヘッダが一致 → 許可
  - 有効な admin JWT (Authorization: Bearer) → require_local_operator_or_admin で許可
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


# Round 258 R7 P0 fix (Codex review):
# 旧コードは `CF-Connecting-IP` を無条件に信用して `_client_ip()` の戻り値とし、
# それを `is_loopback_request()` が `127.0.0.1 / ::1 / localhost` と比較していた。
# attacker が `CF-Connecting-IP: 127.0.0.1` を付ければ:
#   - `allow_select_login()` (analyst/coach JWT 発行)
#   - `allow_legacy_header_auth()` (X-Role 互換経路)
#   - `require_local_operator_or_admin()` (cluster/Ray/SSH dispatch)
#   - `allow_local_file_control()` (ローカル動画パス import)
# が全て突破される P0 級の auth bypass だった。
# 修正: control plane の loopback 判定は **proxy ヘッダを一切信用せず** ASGI socket
# `request.client.host` のみを根拠にする。CF-Connecting-IP は監査ログ/レート制限の
# クライアント IP 表示用途 (`backend.utils.client_ip.trusted_client_ip`) にのみ残す。


def _socket_client_ip(request: Request) -> str:
    """ASGI socket レベルの true client host を返す (proxy ヘッダ無視)。"""
    return request.client.host if request.client else ""


def _client_ip(request: Request) -> str:
    """[非推奨] proxy ヘッダ込みのクライアント IP。loopback 判定には使わないこと。

    レート制限や監査ログの「見かけの送信元 IP 表示」用途のみ。
    現在の callers のうち control plane の判定経路は `_socket_client_ip` を使い、
    残りの「表示」用途のみ trusted_client_ip 経由にする。
    """
    from backend.utils.client_ip import trusted_client_ip
    return trusted_client_ip(request, default="")


# PUBLIC_MODE=True または ENVIRONMENT=production では空文字・testclient を
# loopback 扱いしない（Cloudflare で CF-Connecting-IP が剥がれるような異常経路
# や設定ミスで攻撃者が loopback バイパスを得るのを阻止する・多層防御）。
def _is_production_mode() -> bool:
    from backend.config import settings as _s
    return bool(getattr(_s, "PUBLIC_MODE", False)) or (getattr(_s, "ENVIRONMENT", "") == "production")


def _normalize_ip(ip: str) -> str:
    """Round 258 R8 P0/P1 fix: IPv4-mapped IPv6 (`::ffff:127.0.0.1` 等) を IPv4 文字列に正規化。

    socket は AF_INET6 listen 時に IPv4 接続も `::ffff:<ipv4>` 形式で渡す。
    この値を旧コードは `"127.0.0.1"` と直接比較していたため:
      - 本物の loopback 接続 (`::ffff:127.0.0.1`) を loopback 扱いしない (機能 DoS)
      - 運用者が prefix list に `::ffff:192.168.100.` を「修正」追加すると、
        逆に IPv6 listener に届いた任意 IPv4 が trusted-subnet 扱い化する
    両方の罠を一括で塞ぐため、比較前に必ず IPv4-mapped を unmap する。
    """
    if not ip:
        return ip
    try:
        import ipaddress as _ipa
        addr = _ipa.ip_address(ip)
        if isinstance(addr, _ipa.IPv6Address) and addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
    except (ValueError, TypeError):
        pass
    return ip


def is_loopback_request(request: Request) -> bool:
    """リクエスト元が loopback アドレスかどうかを返す。

    Round 258 R7 P0 fix (Codex): proxy ヘッダ無視で socket IP のみを根拠にする。
    Round 258 R8 P0/P1 fix: IPv4-mapped IPv6 (`::ffff:127.0.0.1`) を正規化してから判定。

    本番環境（PUBLIC_MODE=True または ENVIRONMENT=production）では
    `""` や `"testclient"` を loopback 扱いしない。開発/テスト時のみ許容する。
    """
    ip = _normalize_ip(_socket_client_ip(request))
    if ip in ("127.0.0.1", "::1", "localhost"):
        return True
    # ipaddress 経由で is_loopback も確認 (defense in depth: ::1 表記揺れ対応)
    try:
        import ipaddress as _ipa
        if _ipa.ip_address(ip).is_loopback:
            return True
    except (ValueError, TypeError):
        pass
    # 開発・テスト環境のみ空文字と "testclient" を loopback 扱い
    if not _is_production_mode():
        return ip in ("", "testclient")
    return False


def is_trusted_cluster_request(request: Request) -> bool:
    """リクエスト元が信頼済みクラスタサブネットかどうかを返す。

    Round 258 R7 P0 fix (Codex): subnet 判定も socket IP のみで行う。
    Round 258 R8 P0/P1 fix: IPv4-mapped IPv6 を unmap してから prefix 比較。
    `CF-Connecting-IP: 192.168.100.1` 等で trusted subnet を偽装する経路を遮断。
    """
    ip = _normalize_ip(_socket_client_ip(request))
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
    """X-Role ヘッダーフォールバックを許可するか。
    SS_OPERATOR_TOKEN が設定されている場合は loopback **かつ** token 一致を要求する。
    未設定 (dev) では loopback のみ許可 (後方互換)。
    """
    if not is_loopback_request(request):
        return False
    if _OPERATOR_TOKEN:
        return _has_valid_operator_token(request)
    return True


def allow_select_login(request: Request) -> bool:
    """grant_type=select ログインを許可するか。
    backend が動作するホストへ SSH ラテラルムーブメント等で侵入した攻撃者が
    loopback だけを根拠に admin/analyst JWT を発行できないよう、SS_OPERATOR_TOKEN
    を併用した二要素ガードを採用する。

    - SS_OPERATOR_TOKEN 未設定 (dev): loopback のみ許可 (Electron PIN 選択 UX 維持)
    - SS_OPERATOR_TOKEN 設定済 (production 推奨): loopback **かつ** X-Operator-Token 一致

    Electron 側は backend 起動時の .env から SS_OPERATOR_TOKEN を読み、
    `X-Operator-Token` ヘッダで自動付与する。攻撃者は backend ホストの
    .env ファイル読み取り権限まで掌握しない限り token を知り得ない。
    """
    if not is_loopback_request(request):
        return False
    if _OPERATOR_TOKEN:
        return _has_valid_operator_token(request)
    return True


def allow_seed_admin(request: Request) -> bool:
    """bootstrap admin 自動作成を許可するか。
    select login と同じく、SS_OPERATOR_TOKEN が設定済みなら token 一致も要求する。
    """
    if not is_loopback_request(request):
        return False
    if _OPERATOR_TOKEN:
        return _has_valid_operator_token(request)
    return True


def _is_admin_jwt(request: Request) -> bool:
    """Bearer JWT が有効かつ role=admin であれば True。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth[7:]
    from backend.utils.jwt_utils import verify_token
    payload = verify_token(token)
    return bool(payload and payload.get("role") == "admin")


def require_local_operator_or_admin(request: Request) -> None:
    """クラスタ制御操作のアクセスポリシー。

    loopback・信頼済みサブネット・operator token に加えて
    有効な admin JWT からの外部アクセスも許可する。
    ローカルファイル実行など loopback 限定にすべき操作には
    require_local_or_operator_token を引き続き使用すること。
    """
    if is_loopback_request(request):
        return
    if is_trusted_cluster_request(request):
        return
    if _has_valid_operator_token(request):
        return
    if _is_admin_jwt(request):
        return
    raise HTTPException(
        status_code=403,
        detail="この操作はローカル・信頼済みネットワーク・管理者ログインのいずれかが必要です",
    )


def allow_local_file_control(request: Request) -> bool:
    """ローカルファイルパス実行を許可するか。loopback または trusted cluster。"""
    return is_loopback_request(request) or is_trusted_cluster_request(request)
