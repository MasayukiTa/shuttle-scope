"""Escalation policy for auto-banning (R45+).

方針:
  - 既定は ban せず maze で泳がせる (R45 の "永遠に泳がせる" 戦略)
  - ただし帯域・origin リソースを浪費しすぎる相手 (= 大量に honeytoken /
    canary を踏んでくる相手) は **短時間の TTL 付き ban** で edge から弾く
  - VPN / Tor / CGNAT / unknown ASN は cf_ban_policy が managed_challenge
    までに丸めるので、ここで仮に "block" を選んでも誤 ban 事故にはならない

公開 API:
  - record_hit_and_decide(ip, kind) → Optional[dict]
       閾値を**今ちょうどまたいだ**ときだけ {"ttl_sec": N, "confidence": ...}
       を返す。それ以外は None。

閾値 (kind 別 hit 数):
  honeytoken 10 → 30s  block
  honeytoken 100 → 600s block
  honeytoken 1000 → 3600s block
  canary 30 → 60s  block
  canary 300 → 600s block
  decoy_maze 500 → 60s  block
  decoy_maze 3000 → 600s block
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


# (kind, threshold) → (ttl_sec, confidence)
_TIERS: list[tuple[str, int, int, str]] = [
    # 高 → 低 で評価。先に大きい方を見つけたら return。
    ("honeytoken", 1000, 3600, "critical"),
    ("honeytoken",  100,  600, "critical"),
    ("honeytoken",   10,   30, "critical"),
    ("canary",      300,  600, "medium"),
    ("canary",       30,   60, "medium"),
    ("decoy_maze", 3000,  600, "low"),
    ("decoy_maze",  500,   60, "low"),
]


# ip -> {kind: count}
_counts: dict[str, dict[str, int]] = {}
# (ip, kind) で「最後にどの threshold をまたいだか」を覚える (再発火防止)
_last_tier: dict[tuple[str, str], int] = {}
_lock = threading.Lock()

# 1 週間で counter を expire
_TTL_SEC = 7 * 24 * 3600
_last_seen: dict[str, float] = {}


def record_hit_and_decide(ip: Optional[str], kind: str) -> Optional[dict]:
    """hit を 1 件加算し、新たに閾値を跨いだなら ban 指示を返す。

    1 回ごとに ban を再発火しないよう、(ip, kind) ペアで「最後に跨いだ
    threshold」を保持する。同じ threshold を再評価しても None を返す。

    返り値: None または {"ttl_sec": int, "confidence": str, "matched": (kind, n)}
    """
    if not ip or ip == "?":
        return None

    now = time.time()
    with _lock:
        # GC
        if len(_counts) > 5000:
            cutoff = now - _TTL_SEC
            for k in list(_last_seen.keys()):
                if _last_seen[k] < cutoff:
                    _counts.pop(k, None)
                    _last_seen.pop(k, None)
                    for kk in list(_last_tier.keys()):
                        if kk[0] == k:
                            _last_tier.pop(kk, None)

        per_ip = _counts.setdefault(ip, {})
        per_ip[kind] = per_ip.get(kind, 0) + 1
        n = per_ip[kind]
        _last_seen[ip] = now

        # 一番大きい matched tier を探す
        for tier_kind, threshold, ttl_sec, conf in _TIERS:
            if tier_kind != kind:
                continue
            if n >= threshold:
                key = (ip, kind)
                last = _last_tier.get(key, 0)
                if threshold > last:
                    _last_tier[key] = threshold
                    return {
                        "ttl_sec": ttl_sec,
                        "confidence": conf,
                        "matched_kind": kind,
                        "matched_threshold": threshold,
                        "current_count": n,
                    }
                # 同 threshold は再発火しない
                return None
    return None


def get_count(ip: str, kind: str) -> int:
    with _lock:
        return _counts.get(ip, {}).get(kind, 0)


def reset_ip(ip: str) -> None:
    """admin の手動 unban 後など、特定 IP のカウンタをリセット。"""
    with _lock:
        _counts.pop(ip, None)
        _last_seen.pop(ip, None)
        for k in list(_last_tier.keys()):
            if k[0] == ip:
                _last_tier.pop(k, None)
