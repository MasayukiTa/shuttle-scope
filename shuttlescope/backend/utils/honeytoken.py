"""Honeytoken detection (R42).

戦略:
  - 本物に酷似した、しかし権限を一切持たない token を仕込んでおく。
  - 漏洩経路 (リポ scrape / DB dump / メモリダンプ / フロント reverse) に
    それぞれ「住所が違う」honeytoken を配ることで、検知時に**どの経路から
    抜かれたか**まで分かるようにする (provenance tagging)。
  - middleware が全 request の Authorization / X-* headers / query を
    検査し、honeytoken と一致したら critical severity で audit + CF ban +
    関連 session 強制 revoke。

設計判断:
  - body 検査はしない。FastAPI の body は stream で 1 回しか読めないため、
    middleware で touch すると後続 router が壊れる。header + query で
    実運用の exfil パターンの 95% 以上はカバーできる。
  - 値は固定 (random 生成しない)。grep で source の意図がトレース可能で
    あることを優先。
  - 本物の token (ss_user_* / 実 JWT) と衝突しないよう、prefix を
    `ss_canary_` で統一する。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Honeytoken 一覧 (provenance タグ付き) ─────────────────────────────────
# value → (label, planted_at)
#   planted_at = この値をどこに撒いたか。検知時に「攻撃者がこの場所から
#                抜いた」ことを示す。実際の植え付けは別ファイル (.env.example,
#                seed 等) で行うが、ここに登録された値がマッチすれば検知できる。
HONEYTOKENS: dict[str, tuple[str, str]] = {
    # リポ scrape 用 (.env.example 等にコミットされる前提)
    "ss_canary_admin_live_a8f3c91b2e5d7a40bf6e2c1d4f9a8b3c": (
        "admin_api_key",
        "repo_scrape",
    ),
    "ss_canary_backup_pass_2025_X8nQv3mZpKr7tL9wYeJfHaBc": (
        "backup_passphrase",
        "repo_scrape",
    ),
    # DB dump 用 (app_settings table に "legacy" として残す前提)
    "ss_canary_video_token_legacy_5fA9c2Bd7eE1fG3hI8jK0l": (
        "video_stream_token",
        "db_dump",
    ),
    "ss_canary_refresh_v1_b7d4e2a8c6f9013579ace02468135790": (
        "refresh_token_legacy",
        "db_dump",
    ),
    # フロント bundle 用 (dead code path に埋める前提)
    "ss_canary_frontend_dbg_W0rK3rPr0duct10nK3y2024XYZ12": (
        "internal_worker_key",
        "frontend_bundle",
    ),
    # メモリ / 設定ファイル ダンプ用 (.env.development 風)
    "ss_canary_internal_xfer_M3m0ryDump_C4n4ry_T0k3n_99": (
        "internal_transfer_token",
        "memory_or_config_dump",
    ),
    # R43: staged honeytoken — 怪しい挙動を踏んだ後だけ response に混入される
    # 動的な餌。これを使ってきた = 攻撃者が我々の response を読んで再利用した
    # 動かぬ証拠 (= "response 観察 + token 再利用" の二段ヒット)。
    "ss_canary_lure_staged_R3sp0nseBait_2026_xY7zQ": (
        "staged_response_lure",
        "staged_in_response",
    ),
}


def detect(value: Optional[str]) -> Optional[tuple[str, str]]:
    """文字列 value が honeytoken と一致したら (label, provenance) を返す。

    部分一致も検知する: `Bearer ss_canary_...` や JSON body 風の埋め込みも
    catch するため、登録 token を value 内に substring として探す。
    """
    if not value:
        return None
    # exact 完全一致を先に試す (低コスト)
    direct = HONEYTOKENS.get(value)
    if direct is not None:
        return direct
    # substring 検索 (Bearer prefix / JSON 埋め込み対応)
    for tok, meta in HONEYTOKENS.items():
        if tok in value:
            return meta
    return None


# ─── 検知時の重複抑止 ─────────────────────────────────────────────────────
# 同一 IP + label が短時間に何度も叩かれた場合に audit / CF ban を毎回
# 走らせると自陣 log が flood するので 10 分 dedup する。
_recent_hits: dict[tuple[str, str], float] = {}
_recent_hits_lock = threading.Lock()
_HIT_DEDUP_WINDOW_SEC = 600


def _should_skip_dedup(ip: str, label: str) -> bool:
    import time
    key = (ip or "?", label)
    with _recent_hits_lock:
        last = _recent_hits.get(key, 0.0)
        now = time.time()
        if (now - last) < _HIT_DEDUP_WINDOW_SEC:
            return True
        _recent_hits[key] = now
        if len(_recent_hits) > 1000:
            cutoff = now - _HIT_DEDUP_WINDOW_SEC * 2
            for k in list(_recent_hits.keys()):
                if _recent_hits[k] < cutoff:
                    del _recent_hits[k]
    return False


def handle_hit(
    *,
    ip: str,
    label: str,
    provenance: str,
    path: str,
    method: str,
    ua_fp: str,
    cf_ray: str,
    country: str,
    where: str,
) -> None:
    """Honeytoken hit を検知した際の共通処理。

    - 監査ログに HMAC chain で書き込み (severity=critical, score=10)
    - critical logger
    - Cloudflare 自動 ban を fire-and-forget で発火
    - admin 系 session の強制 revoke は本物の attack confidence なので別途
      実行 (本実装では log だけにとどめ、運用者の判断で revoke する)

    `where` = "header:Authorization" / "query:token" 等、どこから検出したかの
    トレース情報。
    """
    if _should_skip_dedup(ip, label):
        return

    # ─── audit log ─────────────────────────────────────────────────────
    try:
        from backend.utils.access_log import log_access
        from backend.db.database import SessionLocal
        with SessionLocal() as _db:
            log_access(
                _db,
                "honeytoken_used",
                ip_addr=ip,
                resource_type="honeytoken",
                resource_id=None,
                details={
                    "label": label,
                    "provenance": provenance,
                    "where": where,
                    "path": path,
                    "method": method,
                    "ua_fp": ua_fp,
                    "country": country,
                    "cf_ray": cf_ray,
                    "severity": "critical",
                    "risk_score": 10,
                    "reason_code": "honeytoken_used",
                    "action_taken": "log+cf_block+alert",
                },
            )
    except Exception as exc:
        logger.warning("[honeytoken] audit log failed: %s", exc)

    logger.critical(
        "[honeytoken] USED label=%s provenance=%s where=%s ip=%s country=%s "
        "path=%s method=%s ua_fp=%s ray=%s",
        label, provenance, where, ip, country, path, method, ua_fp, cf_ray,
    )

    # R43: 一度でも honeytoken を踏んだら、以降この IP には staged lure を
    # 仕込むモードに昇格させる。
    try:
        from backend.utils.staged_honeytoken import mark_suspicious
        mark_suspicious(ip, f"honeytoken:{label}")
    except Exception:
        pass

    # ─── R45: escalation policy で TTL 付き ban (honeytoken 10/100/1000) ─
    # honeytoken は kind 別カウンタに加算され、閾値跨ぎ時に TTL 付き ban を
    # 発火する。VPN/Tor/CGNAT は cf_ban_policy で managed_challenge に丸まる。
    # kill-switch: SS_DISABLE_AUTO_CF_BAN=1。
    import os as _os
    if (_os.environ.get("SS_DISABLE_AUTO_CF_BAN") or "").strip() != "1":
        try:
            from backend.utils.escalation_policy import record_hit_and_decide
            decision = record_hit_and_decide(ip, "honeytoken")
            if decision is not None:
                from backend.routers.canary import _trigger_cf_auto_ban
                _trigger_cf_auto_ban(
                    ip, f"honeytoken_used:{label}",
                    confidence=decision["confidence"],
                    ttl_sec=decision["ttl_sec"],
                )
        except Exception as exc:
            logger.warning("[honeytoken] CF ban trigger failed: %s", exc)
