"""Canary / honeypot endpoints + tarpit + auto-ban (Codex deception strategy)。

Round 258 R41 (state-level defense):
  - 正規 user は絶対に叩かない path を実装し、ヒットしたら IP / UA / headers を
    強制 access_log に書き込む (HMAC chain なので改ざん不可)
  - レスポンス前に **tarpit** で sleep して攻撃者のスキャンレートを下げる
  - CF API token があれば **自動で WAF block rule を追加** (best-effort)

法的注意 (重要):
  - "逆攻撃" (active hack-back) は **違法** なので本実装は一切行わない
  - 本実装は **passive defense + active blocking on edge** のみ:
    1. ログを残す (audit chain)
    2. レスポンスを遅らせる (tarpit / 自分のリソース消費は許容)
    3. Cloudflare の WAF API 経由で当該 IP を block する (= 自陣の防壁を上げる)
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger(__name__)

# ─── Canary 用 path (誰も叩かないはず) ────────────────────────────────────────
# Codex addendum: deception strategy
_CANARY_PATHS = {
    "/api/admin/export_all",
    "/api/admin/dump",
    "/api/debug/env",
    "/api/internal/backup/download",
    "/api/internal/secrets",
    "/api/.env",
    "/api/config",
    "/api/.git/config",
    "/api/wp-admin",
    "/api/phpmyadmin",
    "/api/actuator/env",
}

# ─── 自動 ban の重複防止 ───────────────────────────────────────────────────
_recent_bans: dict[str, float] = {}
_recent_bans_lock = threading.Lock()
_BAN_DEDUP_WINDOW_SEC = 600  # 10 分


# ─── Tarpit delay range (random 化で adaptive scanner を検知困難に) ──────────
_TARPIT_MIN_SEC = 2.0
_TARPIT_MAX_SEC = 8.0


def _client_ip(request: Request) -> str:
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
    return request.client.host if request.client else "?"


async def _tarpit() -> None:
    """asyncio.sleep で攻撃者の接続を温存しつつスキャンレートを落とす。
    自分のリソース (1 coroutine 分) は消費するが OS スレッドではないので軽量。
    """
    import random as _r
    delay = _r.uniform(_TARPIT_MIN_SEC, _TARPIT_MAX_SEC)
    await asyncio.sleep(delay)


def _trigger_cf_auto_ban(ip: str, reason: str) -> None:
    """Cloudflare WAF Custom Rule API 経由で当該 IP を block する。

    トークン (`SS_CF_BAN_TOKEN`) と zone id (`SS_CF_ZONE_ID`) が env にあれば実行、
    なければ skip。失敗しても backend 動作には影響しない。
    重複 ban を 10 分間抑止する。
    """
    token = (os.environ.get("SS_CF_BAN_TOKEN") or "").strip()
    zone = (os.environ.get("SS_CF_ZONE_ID") or "").strip()
    if not token or not zone or not ip or ip == "?":
        return

    with _recent_bans_lock:
        last = _recent_bans.get(ip, 0.0)
        if (time.time() - last) < _BAN_DEDUP_WINDOW_SEC:
            return  # 既に最近 ban したので skip
        _recent_bans[ip] = time.time()
        # 軽量 GC
        if len(_recent_bans) > 1000:
            cutoff = time.time() - _BAN_DEDUP_WINDOW_SEC * 2
            for k in list(_recent_bans.keys()):
                if _recent_bans[k] < cutoff:
                    del _recent_bans[k]

    # ban 実行は別 thread で fire-and-forget (request thread を blocking しない)
    def _do_ban():
        try:
            import requests  # type: ignore
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            r = requests.post(
                f"https://api.cloudflare.com/client/v4/zones/{zone}/firewall/access_rules/rules",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "mode": "block",
                    "configuration": {"target": "ip", "value": ip},
                    "notes": f"Auto-ban via canary endpoint: {reason}",
                },
                timeout=10,
                verify=False,  # 企業 MITM 対応
            )
            if r.status_code in (200, 201):
                logger.warning("[canary] CF auto-ban applied: ip=%s reason=%s ray=%s",
                               ip, reason, r.headers.get("cf-ray", ""))
            else:
                logger.warning("[canary] CF auto-ban failed status=%s body=%s",
                               r.status_code, r.text[:200])
        except Exception as exc:
            logger.warning("[canary] CF auto-ban exception: %s", exc)

    threading.Thread(target=_do_ban, daemon=True).start()


async def _canary_response(request: Request, path: str) -> JSONResponse:
    """Canary handler 共通処理: audit log + tarpit + CF ban + 偽 404 を返す。"""
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:200]
    cf_ray = request.headers.get("cf-ray", "")
    method = request.method
    referer = request.headers.get("referer", "")[:200]
    country = request.headers.get("cf-ipcountry", "?")

    # ─── audit log (HMAC chain で改ざん不可) ────────────────────────────
    try:
        from backend.utils.access_log import log_access
        from backend.db.database import SessionLocal
        with SessionLocal() as _db:
            log_access(
                _db,
                "canary_hit",
                ip_addr=ip,
                resource_type="canary",
                resource_id=None,
                details={
                    "path": path,
                    "method": method,
                    "ua": ua,
                    "country": country,
                    "cf_ray": cf_ray,
                    "referer": referer,
                },
            )
    except Exception as exc:
        logger.warning("[canary] audit log failed: %s", exc)

    logger.critical(
        "[canary] HIT path=%s method=%s ip=%s country=%s ua=%s ray=%s",
        path, method, ip, country, ua[:80], cf_ray,
    )

    # ─── CF API 経由で自動 ban (best-effort, async fire-and-forget) ────
    _trigger_cf_auto_ban(ip, f"canary_hit:{path}")

    # ─── tarpit: 攻撃者の接続を温存しつつスキャンレートを下げる ────────
    await _tarpit()

    # ─── 攻撃者には絶対に "canary" だと気付かせない: 404 で偽装 ───────
    return JSONResponse(
        {"detail": "Not Found"},
        status_code=404,
    )


# ─── 各 canary path を register ───────────────────────────────────────────
# OpenAPI に出るのを防ぐため include_in_schema=False。
for _p in _CANARY_PATHS:
    # closure に path を bind
    def _make_handler(captured_path: str):
        async def _handler(request: Request):
            return await _canary_response(request, captured_path)
        return _handler

    # GET / POST どちらでも反応するように両方登録
    router.add_api_route(
        _p,
        _make_handler(_p),
        methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        include_in_schema=False,
        name=f"canary_{_p.replace('/', '_').replace('.', '_')}",
    )
