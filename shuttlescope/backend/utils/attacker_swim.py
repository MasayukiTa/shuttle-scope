"""Attacker swim / behaviour recorder (R44).

設計方針:
  - 攻撃者を 1 発で ban するのではなく、しばらく迷路 (decoy router) に
    泳がせて行動ログを溜める。
  - ログは将来の防御ルール改善 / 攻撃トレンド観察 / WAF rule tuning に使う。
  - 永続化は audit log (HMAC chain) 側に任せ、本 module は in-memory に
    "hit カウンタ" だけ持つ (process 単一プロセス想定で OK)。

公開 API:
  - note_hit(ip, kind, detail) → 通算 hit 数を返す
  - should_apply_cf_action(ip, hits) → CF action を発火すべきか
  - get_profile(ip) → dict (admin 画面表示用)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


# ip -> {"first": ts, "last": ts, "hits": [...], "kinds": {kind: count}}
_profiles: dict[str, dict] = {}
_lock = threading.Lock()

# 単一 profile のサイズ上限
_MAX_HITS_PER_IP = 200
_TTL_SEC = 7 * 24 * 3600  # 1 週間で expire

# 何回 hit したら CF action を発火するか (= 泳がせる長さ)
_SWIM_THRESHOLD_DEFAULT = 5

# critical イベント (honeytoken 使用) は閾値関係なく即発火
_CRITICAL_KINDS = {"honeytoken"}


def note_hit(ip: Optional[str], *, kind: str, detail: str) -> int:
    """この IP の hit を 1 件記録し、累計 hit 数を返す。"""
    if not ip or ip == "?":
        return 0
    now = time.time()
    with _lock:
        prof = _profiles.get(ip)
        if prof is None:
            prof = {"first": now, "last": now, "hits": [], "kinds": {}}
            _profiles[ip] = prof
        prof["last"] = now
        prof["kinds"][kind] = prof["kinds"].get(kind, 0) + 1
        prof["hits"].append({"ts": now, "kind": kind, "detail": detail[:200]})
        if len(prof["hits"]) > _MAX_HITS_PER_IP:
            prof["hits"] = prof["hits"][-_MAX_HITS_PER_IP:]
        total = sum(prof["kinds"].values())

        # 軽量 GC
        if len(_profiles) > 5000:
            cutoff = now - _TTL_SEC
            for k in list(_profiles.keys()):
                if _profiles[k]["last"] < cutoff:
                    del _profiles[k]

    logger.info(
        "[swim] hit ip=%s kind=%s detail=%s total=%d",
        ip, kind, detail[:80], total,
    )
    # R46: 統計集計レイヤにも転送 (in-memory aggregator、別 module で
    # Markov / first-hit / depth カウンタを更新する)。失敗しても note_hit
    # 自体の挙動には影響させない (fail-open)。
    try:
        from backend.utils.attack_pattern import record_hit as _rec
        _rec(ip, detail, kind)
    except Exception:
        pass
    return total


def should_apply_cf_action(ip: Optional[str], hits: int, *,
                            kind: Optional[str] = None) -> bool:
    """泳がせ閾値を超えたら True。critical kind は閾値無視で True。"""
    if kind in _CRITICAL_KINDS:
        return True
    return hits >= _SWIM_THRESHOLD_DEFAULT


def get_profile(ip: Optional[str]) -> Optional[dict]:
    if not ip or ip == "?":
        return None
    with _lock:
        prof = _profiles.get(ip)
        if prof is None:
            return None
        return {
            "ip": ip,
            "first": prof["first"],
            "last": prof["last"],
            "kinds": dict(prof["kinds"]),
            "total_hits": sum(prof["kinds"].values()),
            "recent_hits": list(prof["hits"][-30:]),
        }


def all_profiles_summary(limit: int = 50) -> list[dict]:
    """admin 画面用: hit 数の多い順に top N 件を返す。"""
    with _lock:
        items = [
            (ip, sum(p["kinds"].values()), p["last"], dict(p["kinds"]))
            for ip, p in _profiles.items()
        ]
    items.sort(key=lambda x: x[1], reverse=True)
    return [
        {"ip": ip, "total": total, "last": last, "kinds": kinds}
        for ip, total, last, kinds in items[:limit]
    ]
