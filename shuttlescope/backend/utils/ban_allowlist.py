"""Ban allowlist (R47): attack 自己テスト用の自爆回避層。

目的:
  - 自分で攻撃テストを走らせると honeytoken/canary が即 escalation 閾値に
    達して自分の IP が ban される。テスト中はこれを避けたい。
  - ただし「テスト IP は detection 自体を skip」だと検知ロジックの動作確認に
    ならない。**検知 + 記録は通常通り行うが ban 発火だけ抑止** したい。

設計:
  - 環境変数 `SS_BAN_ALLOWLIST_IPS` (カンマ区切り IP or CIDR) で指定
  - 環境変数 `SS_BAN_ALLOWLIST_HEADER` で「このヘッダがあれば allowlist」を指定
    (例: `X-SS-Attack-Test: <HMAC>` 形式)
  - 環境変数 `SS_BAN_ALLOWLIST_HEADER_SECRET` で header の expected value を指定
  - is_ban_allowlisted(ip, request) で照会
  - allowlist 該当時:
      * attacker_swim.note_hit → 記録する (テストデータ収集に有効)
      * escalation_policy.record_hit_and_decide → None を返す (ban しない)
      * _trigger_cf_auto_ban → 入口で whitelist 扱いで何もしない

注意:
  - SS_BAN_ALLOWLIST_HEADER_SECRET は十分長い random 文字列を使う。
  - 攻撃者が推測して allowlist をすり抜けないよう、header 一致は constant-time。
"""
from __future__ import annotations

import hmac as _hmac
import ipaddress
import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _cached_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    raw = (os.environ.get("SS_BAN_ALLOWLIST_IPS") or "").strip()
    if not raw:
        return ()
    nets = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            if "/" in tok:
                nets.append(ipaddress.ip_network(tok, strict=False))
            else:
                # 単独 IP は /32 (or /128) ネットワークとして扱う
                nets.append(ipaddress.ip_network(tok, strict=False))
        except Exception:
            logger.warning("[ban_allowlist] invalid entry skipped: %r", tok)
    return tuple(nets)


def _ip_allowlisted(ip: Optional[str]) -> bool:
    if not ip or ip == "?":
        return False
    nets = _cached_networks()
    if not nets:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except Exception:
        return False
    for n in nets:
        if addr in n:
            return True
    return False


def _header_allowlisted(headers: dict[str, str] | None) -> bool:
    if not headers:
        return False
    hkey = (os.environ.get("SS_BAN_ALLOWLIST_HEADER") or "").strip()
    secret = (os.environ.get("SS_BAN_ALLOWLIST_HEADER_SECRET") or "").strip()
    if not hkey or not secret:
        return False
    # case-insensitive header lookup
    val = ""
    for k, v in headers.items():
        if k.lower() == hkey.lower():
            val = (v or "").strip()
            break
    if not val:
        return False
    # 一致は constant-time で
    return _hmac.compare_digest(val, secret)


def is_ban_allowlisted(ip: Optional[str], headers: dict[str, str] | None = None) -> bool:
    """ban escalation を skip すべきかを返す。"""
    if _ip_allowlisted(ip):
        return True
    if _header_allowlisted(headers):
        return True
    return False


def clear_cache() -> None:
    """テスト用: env を変更した後にキャッシュをリセット。"""
    _cached_networks.cache_clear()
