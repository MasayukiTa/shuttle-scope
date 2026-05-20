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

import time
import uuid
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.utils.security_log import emit_request_log, emit_security_event


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
                ip, xff = _client_ip(request)
                ua = request.headers.get("user-agent")
                referer = request.headers.get("referer")
                cf_ray = request.headers.get("cf-ray")
                country = request.headers.get("cf-ipcountry")
                user_id = getattr(request.state, "user_id", None)
                query = request.url.query or None
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
