"""Request-level observability + probe detection middlewares.

外部攻撃の判別/フォレンジック用に access_logs (内部アクションのみ) では
カバーできない領域を埋める:

  - RequestLogMiddleware: 全 HTTP リクエストを request_logs に 1 行ずつ追加。
    health check 等の高頻度 endpoint は除外。
  - ProbeDetectionMiddleware: /.env, /wp-admin 等の典型プローブ path を
    早期検知し、security_events に probe_attempt を残してから 404 を返す。
    (実体は普通の 404 だが、検知ロジックをここに集約する)
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.utils.audit_grouping import is_monitoring_self_read
from backend.utils.crawler_policy import ROBOTS_TAG
from backend.utils.security_detectors import record_secret_path_response
from backend.utils.security_log import emit_request_log, emit_security_event, emit_audit_event
from backend.utils.audit_targets import (
    should_audit,
    classify_path,
    action_for_method,
    summarize_body,
)


# 高頻度かつ攻撃判定に寄与しない endpoint は request_log から除外
_SKIP_PATH_PREFIXES: tuple[str, ...] = (
    "/api/health",
    "/api/auth/heartbeat",  # device heartbeat (常時 polling)
    "/api/cluster/status",  # cluster monitor polling
    "/static/",
    "/assets/",
    "/favicon",
)

# プローブ判定: 完全一致 / prefix で典型攻撃 path を捕捉
# Cloudflare 側でも止めるが、二重検知して相関できるよう backend にも残す
_PROBE_EXACT: frozenset[str] = frozenset({
    "/.env", "/.env.local", "/.env.production", "/.env.development",
    "/.git/config", "/.git/HEAD", "/.git/index",
    "/admin", "/admin/", "/admin.php", "/administrator", "/administrator/",
    "/phpmyadmin", "/phpmyadmin/", "/pma", "/pma/",
    "/wp-admin", "/wp-admin/", "/wp-login.php", "/xmlrpc.php",
    "/cgi-bin/", "/server-status", "/server-info",
    "/etc/passwd", "/proc/self/environ",
    "/owa/", "/ews/", "/autodiscover/",
    "/sftp-config.json", "/config.json", "/config.php",
    "/backup.zip", "/backup.tar.gz", "/db.sql", "/database.sql",
    "/.htaccess", "/.htpasswd",
    "/aws.json", "/credentials", "/.aws/credentials",
    "/jenkins", "/jenkins/", "/.docker/config.json",
})

_PROBE_PREFIX: tuple[str, ...] = (
    "/.git/",
    "/.svn/",
    "/.hg/",
    "/.idea/",
    "/.vscode/",
    "/wp-content/",
    "/wp-includes/",
    "/wp-config",
    "/cgi-bin/",
    "/phpmyadmin/",
    "/owa/",
    "/ews/",
    "/_ignition/",            # Laravel debug RCE
    "/actuator",              # Spring Boot
    "/druid/",                # Apache Druid
    "/manager/html",          # Tomcat
)


def _looks_like_probe(path: str) -> bool:
    if not path:
        return False
    p = path.lower()
    if p in _PROBE_EXACT:
        return True
    for pre in _PROBE_PREFIX:
        if p.startswith(pre):
            return True
    return False


def _truncate(s: str | None, n: int) -> str | None:
    if s is None:
        return None
    s = str(s)
    return s if len(s) <= n else s[:n]


def _client_ip(request: Request) -> tuple[str | None, str | None]:
    """(ip, xff) を返す。Cloudflare 経由なら CF-Connecting-IP 優先。"""
    h = request.headers
    xff = h.get("x-forwarded-for")
    cf = h.get("cf-connecting-ip")
    ip = cf or (xff.split(",")[0].strip() if xff else None) or (request.client.host if request.client else None)
    return ip, xff


def _authenticated_user_id(request: Request) -> int | None:
    """User id of the caller when a valid bearer token is present, else None.

    request_logs.user_id was empty on every row because nothing ever set
    request.state.user_id (the old code only read that attribute). The id comes
    from a verified token, never from an unverified claim, so a forged token
    cannot poison the forensic column."""
    uid = getattr(request.state, "user_id", None)
    if uid:
        return uid
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        from backend.utils.jwt_utils import verify_token
        payload = verify_token(auth[7:].strip())
        sub = str((payload or {}).get("sub", ""))
        return int(sub) if sub.isdigit() and int(sub) > 0 else None
    except Exception:
        return None


def _is_decoy_response(request: Request, response: Response | None) -> bool:
    """True only for the deliberate decoy (decoy_maze marks request.state, and the
    fake .env also sends `X-Honeyfile: yes`)."""
    if getattr(request.state, "is_decoy", False):
        return True
    return response is not None and response.headers.get("x-honeyfile", "").lower() == "yes"


class RequestLogMiddleware(BaseHTTPMiddleware):
    """全 HTTP request を request_logs に記録 (一部 path は除外)。"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # 高頻度かつ攻撃判定に寄与しない path は skip
        if any(path.startswith(p) for p in _SKIP_PATH_PREFIXES):
            return await call_next(request)

        # request_id を生成 (後続の error_logs と correlate するため)
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id

        start = time.perf_counter()
        status = 500
        response: Response | None = None
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            try:
                # 監視画面が履歴を読むための成功した GET は記録しない
                # (監視画面を開くだけで request_logs が増えるのを防ぐ)。
                skip_log = is_monitoring_self_read(request.method, path, status)
                ip, xff = _client_ip(request)
                ua = request.headers.get("user-agent")
                referer = request.headers.get("referer")
                cf_ray = request.headers.get("cf-ray")
                country = request.headers.get("cf-ipcountry")
                user_id = _authenticated_user_id(request)
                query = request.url.query or None
                # Secret-path 200 / decoy hit. Runs for every response FastAPI
                # produced (this middleware is the outermost one).
                # Every decoy response (and decoy 404) tells crawlers to keep out.
                if response is not None and getattr(request.state, "is_decoy", False):
                    response.headers["X-Robots-Tag"] = ROBOTS_TAG
                # A crawler on a decoy was already recorded as crawler_decoy_visit.
                if status == 200 and not getattr(request.state, "is_crawler", False):
                    record_secret_path_response(
                        path=path,
                        status=status,
                        is_decoy=_is_decoy_response(request, response),
                        ip=ip,
                        method=request.method,
                        ua=_truncate(ua, 255),
                        request_id=request_id,
                        country=_truncate(country, 2),
                        authenticated=user_id is not None,
                    )
                if not skip_log:
                    emit_request_log(
                        method=request.method,
                        path=path,
                        status=status,
                        duration_ms=duration_ms,
                        query=_truncate(query, 1024),
                        user_id=user_id,
                        ip_addr=ip,
                        xff=_truncate(xff, 255),
                        ua=_truncate(ua, 255),
                        referer=_truncate(referer, 255),
                        request_id=request_id,
                        cf_ray=_truncate(cf_ray, 32),
                        country=_truncate(country, 2),
                    )
                # response header にも request_id を返す (運用での突き合わせ用)
                if response is not None:
                    response.headers["x-request-id"] = request_id
            except Exception:
                pass


class ProbeDetectionMiddleware(BaseHTTPMiddleware):
    """既知の攻撃 probe path を early-detect → security_events に記録 → 404。

    HoneytokenDetectionMiddleware は header/query 内 token 値だけを見るので、
    純粋な path probing (e.g. /.env, /wp-admin) は捕捉できない。本 middleware
    がその穴を埋める。
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if _looks_like_probe(path):
            ip, _xff = _client_ip(request)
            request_id = getattr(request.state, "request_id", None)
            try:
                emit_security_event(
                    "probe_attempt",
                    severity="warn",
                    ip_addr=ip,
                    path=path,
                    method=request.method,
                    ua=_truncate(request.headers.get("user-agent"), 255),
                    request_id=request_id,
                    details={"query": request.url.query[:512] if request.url.query else None},
                )
            except Exception:
                pass
            # 攻撃者にこちらの存在を匂わせない: 単純な 404 を返す
            return Response(status_code=404, content=b"Not Found", media_type="text/plain")
        return await call_next(request)


# body ハッシュ化のために読み取る上限。これを超える body はハッシュを取らず
# (fields/count/hash を None にして) 行だけ残す。strokes batch の実測最大 ~180KB を
# 十分カバーしつつ、動画 multipart のような巨大 body をメモリに載せない。
_AUDIT_BODY_MAX_BYTES = 512 * 1024

_audit_log = logging.getLogger("shuttlescope.audit_events")


class AuditEventMiddleware(BaseHTTPMiddleware):
    """対象エンティティ(試合/セット/ラリー/ストローク/選手/ユーザー/設定)の
    作成・更新・削除が成功したとき、audit_events に 1 行残す。

    「誰が・いつ・どの entity に・どの操作を・どのフィールドに対して行ったか」を
    漏れなく記録するための共通フック。個別の router に log_access を足して回る
    方式は書き漏れが構造的に避けられない(実測: HEAD 時点で matches/sets/rallies/
    strokes/settings/conditions は変更系なのに log_access 呼び出し 0)。そこで
    横断的な middleware 1 箇所で担保する。

    値は保存しない。変更内容は changed_fields(列名のみ)/field_count/body_hash に
    要約する(理由と測定は AuditEvent モデルの docstring を参照)。

    本処理との独立性: 監査書き込みは emit_audit_event が別 DB セッションで行い、
    失敗しても元のレスポンスには影響しない。
    """

    async def dispatch(self, request: Request, call_next):
        method = request.method
        path = request.url.path

        # 対象メソッド以外は body を触らず素通し(GET 等のホットパスを汚さない)。
        if method.upper() not in ("POST", "PUT", "PATCH", "DELETE"):
            return await call_next(request)
        if classify_path(path) is None:
            return await call_next(request)

        # body を先に読む。Starlette は Request.body() を request._body に
        # キャッシュし、下流ハンドラの再読み取りでも同じ bytes を返すため、
        # ここで読んでも後段の FastAPI バリデーションは壊れない。
        # ただし Content-Length が上限超なら読まない(巨大 multipart 保護)。
        raw: bytes | None = None
        try:
            cl = request.headers.get("content-length")
            too_big = cl is not None and cl.isdigit() and int(cl) > _AUDIT_BODY_MAX_BYTES
            if not too_big:
                raw = await request.body()
                if raw is not None and len(raw) > _AUDIT_BODY_MAX_BYTES:
                    raw = None  # 実測で超過したら破棄(ハッシュ無し)
        except Exception:
            raw = None

        response = await call_next(request)

        try:
            status = response.status_code
            if should_audit(method, path, status):
                cls = classify_path(path)
                entity_type, entity_id = (cls if cls else (None, None))
                action = action_for_method(method)
                fields, count, body_hash = summarize_body(raw)
                ip, _xff = _client_ip(request)
                request_id = getattr(request.state, "request_id", None)
                # GlobalAuthMiddleware(内側)が request.state に user_id を載せる。
                # AuditEventMiddleware は最外なので call_next 後に読めば確定済み。
                # state に無い場合は検証済みトークンから解決する(_caller_* は
                # 自己申告ではなく verify_token 済みの値のみを返す)。
                user_id = getattr(request.state, "user_id", None)
                if user_id is None:
                    user_id = _caller_user_id(request)
                role = getattr(request.state, "role", None) or _caller_role(request)
                emit_audit_event(
                    action=action or "",
                    method=method,
                    path=path,
                    status=status,
                    user_id=user_id,
                    role=role,
                    ip_addr=ip,
                    request_id=request_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    changed_fields=fields,
                    field_count=count,
                    body_hash=body_hash,
                )
        except Exception as exc:
            # 監査の失敗で本来のレスポンスを壊さない。ただし無言にはしない。
            _audit_log.warning("AuditEventMiddleware failed: %s (path=%s)", exc, path)
        return response


def _caller_role(request: Request) -> str | None:
    """呼び出し元の role を解決する。auth.get_auth と同じ入口を使い、
    自己申告(X-Role)ではなく検証済みトークンの role を優先する。失敗時 None。"""
    try:
        from backend.utils.auth import get_auth
        ctx = get_auth(request)
        return getattr(ctx, "role", None)
    except Exception:
        return None


def _caller_user_id(request: Request) -> int | None:
    """呼び出し元の user_id を解決する。request.state に無い場合のフォールバック。
    Authorization の Bearer を verify_token で検証した sub からのみ取り、
    偽造トークンが監査の主体列を汚さないようにする。失敗時 None。"""
    try:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return None
        from backend.utils.jwt_utils import verify_token
        payload = verify_token(auth[7:].strip())
        sub = str((payload or {}).get("sub", ""))
        return int(sub) if sub.isdigit() and int(sub) > 0 else None
    except Exception:
        return None
