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
import hashlib
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
# Codex policy では 1-5s 推奨だが、自陣 self-DoS が起きない範囲で長めに置く方が
# scanner のスループットを落とせる。代わりに同時実行数を semaphore で cap して
# 自陣 fd / event-loop 占有を防ぐ。
_TARPIT_MIN_SEC = 2.0
_TARPIT_MAX_SEC = 8.0

# 同時 tarpit 数の上限 (self-DoS 防止)。これを超えたら sleep せずに即 404 を返す。
_TARPIT_MAX_CONCURRENT = 32
_tarpit_sem = asyncio.Semaphore(_TARPIT_MAX_CONCURRENT)


def _ua_fingerprint(ua: str) -> str:
    """UA 全文を残すと PII / log volume 問題があるので 12 hex に短縮 hash 化。"""
    if not ua:
        return ""
    return hashlib.sha256(ua.encode("utf-8", errors="replace")).hexdigest()[:12]


def _client_ip(request: Request) -> str:
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
    return request.client.host if request.client else "?"


async def _tarpit() -> bool:
    """asyncio.sleep で攻撃者の接続を温存しつつスキャンレートを落とす。
    自分のリソース (1 coroutine 分) は消費するが OS スレッドではないので軽量。

    semaphore が空きを返さない (= 同時 tarpit 数が上限) 場合は sleep を諦めて
    即 return する。これにより flood 系の攻撃で self-DoS にならない。
    True=tarpit 適用, False=cap 越えで skip。
    """
    import random as _r
    if _tarpit_sem.locked() and _tarpit_sem._value <= 0:  # type: ignore[attr-defined]
        return False
    try:
        async with _tarpit_sem:
            delay = _r.uniform(_TARPIT_MIN_SEC, _TARPIT_MAX_SEC)
            await asyncio.sleep(delay)
            return True
    except Exception:
        return False


def _trigger_cf_auto_ban(ip: str, reason: str, *, confidence: str = "medium",
                          asn: Optional[int] = None,
                          ttl_sec: int = 600) -> None:
    """Cloudflare WAF Custom Rule API 経由で IP に対し block / challenge を適用。

    R44: VPN / Tor / CGNAT などの共有出口を **絶対に永久 block しない** ため
    ASN ベースの policy を経由する。最終 mode は cf_ban_policy.decide_cf_mode
    が決定し、"whitelist" の場合は何もしない。

    R45: ttl_sec を受け取り、TTL 経過後に threading.Timer で自動的に
    CF rule を DELETE する。CF Access Rules は native TTL 非対応なので
    アプリ側でスケジュール削除する。process 再起動で Timer は消えるが、
    その場合は CF dashboard で残骸 rule を notes フィルタで掃除できる。

    トークン (`SS_CF_BAN_TOKEN`) と zone id (`SS_CF_ZONE_ID`) が env にあれば実行、
    なければ skip。失敗しても backend 動作には影響しない。
    重複適用を 10 分間抑止する。
    """
    token = (os.environ.get("SS_CF_BAN_TOKEN") or "").strip()
    zone = (os.environ.get("SS_CF_ZONE_ID") or "").strip()
    if not token or not zone or not ip or ip == "?":
        return

    # ─── R44: VPN / Tor / CGNAT safe mode 判定 ─────────────────────────
    try:
        from backend.utils.cf_ban_policy import decide_cf_mode
        mode = decide_cf_mode(ip=ip, asn=asn, confidence=confidence)
    except Exception:
        mode = "challenge"  # 判定不能なら絶対に block しない (誤 ban 回避)
    if mode == "whitelist":
        logger.info("[canary] CF ban skipped (whitelist): ip=%s", ip)
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
                    "mode": mode,  # R44: ASN-aware (block / challenge / managed_challenge)
                    "configuration": {"target": "ip", "value": ip},
                    "notes": (
                        f"Auto-ban via canary: {reason} "
                        f"(mode={mode} ttl={ttl_sec}s "
                        f"expires={int(time.time()) + ttl_sec})"
                    ),
                },
                timeout=10,
                verify=False,  # 企業 MITM 対応
            )
            if r.status_code in (200, 201):
                rule_id = ""
                try:
                    rule_id = (r.json() or {}).get("result", {}).get("id", "") or ""
                except Exception:
                    pass
                logger.warning(
                    "[canary] CF auto-ban applied: ip=%s reason=%s ray=%s "
                    "rule_id=%s ttl=%ds",
                    ip, reason, r.headers.get("cf-ray", ""), rule_id, ttl_sec,
                )
                # ─── R45: TTL 経過後に rule を DELETE する ────────────
                if rule_id and ttl_sec > 0:
                    threading.Timer(
                        ttl_sec, _do_cf_unban_by_id, args=[rule_id, ip]
                    ).start()
            else:
                logger.warning("[canary] CF auto-ban failed status=%s body=%s",
                               r.status_code, r.text[:200])
        except Exception as exc:
            logger.warning("[canary] CF auto-ban exception: %s", exc)

    threading.Thread(target=_do_ban, daemon=True).start()


def _do_cf_unban_by_id(rule_id: str, ip: str) -> None:
    """TTL 経過時の CF rule DELETE。fire-and-forget。"""
    token = (os.environ.get("SS_CF_BAN_TOKEN") or "").strip()
    zone = (os.environ.get("SS_CF_ZONE_ID") or "").strip()
    if not token or not zone or not rule_id:
        return
    try:
        import requests  # type: ignore
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.delete(
            f"https://api.cloudflare.com/client/v4/zones/{zone}"
            f"/firewall/access_rules/rules/{rule_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
            verify=False,
        )
        logger.warning(
            "[canary] CF auto-unban: ip=%s rule_id=%s status=%s",
            ip, rule_id, r.status_code,
        )
        # dedup 解除 (次回また escalation が走った時に再 ban できるよう)
        with _recent_bans_lock:
            _recent_bans.pop(ip, None)
    except Exception as exc:
        logger.warning("[canary] CF auto-unban exception: %s", exc)


async def _canary_response(request: Request, path: str) -> JSONResponse:
    """Canary handler 共通処理: audit log + tarpit + CF ban + 偽 404 を返す。"""
    ip = _client_ip(request)
    ua_raw = request.headers.get("user-agent", "")[:200]
    ua_fp = _ua_fingerprint(ua_raw)
    cf_ray = request.headers.get("cf-ray", "")
    method = request.method
    referer = request.headers.get("referer", "")[:200]
    country = request.headers.get("cf-ipcountry", "?")

    # ─── audit log (HMAC chain で改ざん不可) ────────────────────────────
    # Codex policy 準拠 schema: severity / reason_code / action_taken / risk_score
    # を含める。生 UA は hash 化済み (ua_fp)、本物の token は記録しない。
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
                    "ua_fp": ua_fp,
                    "country": country,
                    "cf_ray": cf_ray,
                    "referer": referer,
                    "severity": "high",
                    "risk_score": 8,
                    "reason_code": "canary_path_hit",
                    "action_taken": "tarpit+cf_block+log",
                },
            )
    except Exception as exc:
        logger.warning("[canary] audit log failed: %s", exc)

    logger.critical(
        "[canary] HIT path=%s method=%s ip=%s country=%s ua_fp=%s ray=%s",
        path, method, ip, country, ua_fp, cf_ray,
    )

    # R43: canary 踏んだ IP は以降 staged honeytoken の対象に昇格。
    # CF ban が edge で発火するが、IP rotation で再来訪してくる可能性が
    # あるので IP 単位での fingerprint を残しておく。
    try:
        from backend.utils.staged_honeytoken import mark_suspicious
        mark_suspicious(ip, f"canary:{path}")
    except Exception:
        pass

    # ─── R45: 「永遠に泳がせる」 + escalation 閾値で TTL 付き ban ─────
    # R47: 自己テスト用 allowlist (IP / header) があれば ban 経路を skip。
    # 記録 (note_hit) は通常どおり行う。
    try:
        from backend.utils.attacker_swim import note_hit
        from backend.utils.escalation_policy import record_hit_and_decide
        from backend.utils.ban_allowlist import is_ban_allowlisted
        note_hit(ip, kind="canary", detail=path)
        if (os.environ.get("SS_DISABLE_AUTO_CF_BAN") or "").strip() != "1":
            if not is_ban_allowlisted(ip, dict(request.headers)):
                decision = record_hit_and_decide(ip, "canary")
                if decision is not None:
                    _trigger_cf_auto_ban(
                        ip, f"canary_hit:{path}",
                        confidence=decision["confidence"],
                        ttl_sec=decision["ttl_sec"],
                    )
    except Exception:
        pass

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
