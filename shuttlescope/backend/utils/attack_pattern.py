"""Attack pattern aggregator (R46).

設計方針:
  - **生ログは access_log (HMAC chain) と attacker_swim (in-memory per-IP)
    が既にやっている**。本 module はそれを汚さず、別レイヤで「統計だけ」を
    in-memory に保持する。
  - 同じパターンが何度繰り返されても新たな row を増やさない (= counter を
    インクリメントするだけ) なので、storage は O(unique patterns) で済む。
  - 攻撃者の典型的な動き:
      1. 最初に何を叩いてくるか (= entry distribution / first-hit)
      2. その後どこへ動くか (= 1-step path transition / Markov)
      3. 何ステップで離脱・深掘りするか (= depth distribution)
    を統計として出すための最低限のカウンタを保持する。
  - 永続化: process 起動中は in-memory、`flush_to_file()` で JSON にダンプ
    可能。startup で前回ファイルを読み戻すこともできる (round-trip)。

公開 API:
  - record_hit(ip, path, kind) — 攻撃者の 1 hit を記録、統計を更新
  - snapshot() — 現状を dict で返す (admin 観測 / CLI viewer 用)
  - flush_to_file(path) / load_from_file(path) — 永続化
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Optional

logger = logging.getLogger(__name__)


# ─── 集計対象パスの正規化 ────────────────────────────────────────────────
# 「同じパターン」の判定を緩くするため一定の path 正規化を行う。
# 例:
#   /admin/legacy/v1/users/v2/config/v3/archive  →  /admin/legacy/*/users/*/config/*/archive
# 数値・UUID 風 token は `*` に丸めて Markov ノード爆発を防ぐ。
import re as _re

_UUID_RE = _re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}")
_INT_RE = _re.compile(r"^\d{1,}$")
_HEX_RE = _re.compile(r"^[0-9a-fA-F]{8,}$")
_VER_RE = _re.compile(r"^v\d+$", flags=_re.IGNORECASE)


def normalize_path(raw: str) -> str:
    """path を集計用に正規化する。
    - query string を落とす
    - 数値 / 長 hex / UUID は `*` に
    - 末尾 / は 1 個に
    - `v1` `v2` 等のバージョン文字列は残す (攻撃者が enumerate する典型)
    """
    if not raw:
        return "/"
    # クエリ落とし
    p = raw.split("?", 1)[0]
    # UUID を `*`
    p = _UUID_RE.sub("*", p)
    parts = [seg for seg in p.split("/") if seg != ""]
    out = []
    for seg in parts:
        if _VER_RE.match(seg):
            out.append(seg.lower())
        elif _INT_RE.match(seg):
            out.append("*")
        elif _HEX_RE.match(seg):
            out.append("*")
        else:
            out.append(seg)
    return "/" + "/".join(out) if out else "/"


# ─── 状態 ─────────────────────────────────────────────────────────────────

_lock = threading.Lock()

# IP -> deque of last N normalized paths (Markov 用のショートメモリ)
_HISTORY_LEN = 10
_recent_paths: dict[str, deque[str]] = {}

# 集計カウンタ
# {normalized_path: count}
_first_hits: dict[str, int] = defaultdict(int)
# {(from, to): count}
_transitions: dict[tuple[str, str], int] = defaultdict(int)
# {normalized_path: count}  (kind 別ではなく総 hit 数)
_path_hits: dict[str, int] = defaultdict(int)
# {kind: count}
_kind_counts: dict[str, int] = defaultdict(int)
# {(path, kind): count}
_path_kind_counts: dict[tuple[str, str], int] = defaultdict(int)
# IP -> depth (= 観測された path の通算数)
_depth_by_ip: dict[str, int] = defaultdict(int)
# 集計開始時刻
_started_at = time.time()


def record_hit(ip: Optional[str], path: str, kind: str) -> None:
    """1 hit を記録し、Markov / first-hit / depth カウンタを更新する。"""
    if not ip:
        ip = "?"
    norm = normalize_path(path)
    with _lock:
        history = _recent_paths.setdefault(ip, deque(maxlen=_HISTORY_LEN))
        if len(history) == 0:
            _first_hits[norm] += 1
        else:
            _transitions[(history[-1], norm)] += 1
        history.append(norm)
        _path_hits[norm] += 1
        _kind_counts[kind] += 1
        _path_kind_counts[(norm, kind)] += 1
        _depth_by_ip[ip] += 1


def snapshot() -> dict:
    """現状の統計を dict で返す。CLI viewer / admin 用。"""
    with _lock:
        top_first = sorted(_first_hits.items(), key=lambda x: -x[1])[:30]
        top_paths = sorted(_path_hits.items(), key=lambda x: -x[1])[:50]
        top_transitions = sorted(_transitions.items(), key=lambda x: -x[1])[:50]
        depth_buckets = {
            "1": 0, "2-5": 0, "6-20": 0, "21-100": 0, "100+": 0,
        }
        for v in _depth_by_ip.values():
            if v == 1:
                depth_buckets["1"] += 1
            elif v <= 5:
                depth_buckets["2-5"] += 1
            elif v <= 20:
                depth_buckets["6-20"] += 1
            elif v <= 100:
                depth_buckets["21-100"] += 1
            else:
                depth_buckets["100+"] += 1
        return {
            "started_at": _started_at,
            "uptime_sec": int(time.time() - _started_at),
            "total_ips": len(_recent_paths),
            "total_hits": sum(_path_hits.values()),
            "top_first_hits": [{"path": p, "count": c} for p, c in top_first],
            "top_paths": [{"path": p, "count": c} for p, c in top_paths],
            "top_transitions": [
                {"from": a, "to": b, "count": c}
                for (a, b), c in top_transitions
            ],
            "kind_counts": dict(_kind_counts),
            "depth_distribution": depth_buckets,
        }


def flush_to_file(path: str) -> None:
    """snapshot を JSON ファイルに書き出す。atomic write。"""
    snap = snapshot()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        logger.warning("[attack_pattern] flush failed: %s", exc)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def load_from_file(path: str) -> bool:
    """startup 時に前回 snapshot を読み戻す (counter のみ復元)。

    Markov 履歴 (_recent_paths) は復元しない (per-IP の short memory なので
    restart で消えても支障なし)。
    """
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("[attack_pattern] load failed: %s", exc)
        return False
    with _lock:
        for item in data.get("top_first_hits", []):
            _first_hits[item["path"]] += int(item.get("count", 0))
        for item in data.get("top_paths", []):
            _path_hits[item["path"]] += int(item.get("count", 0))
        for item in data.get("top_transitions", []):
            _transitions[(item["from"], item["to"])] += int(item.get("count", 0))
        for k, v in (data.get("kind_counts") or {}).items():
            _kind_counts[k] += int(v)
    return True


# ─── 定期 flush thread (opt-in) ─────────────────────────────────────────
_flush_timer: Optional[threading.Timer] = None
_flush_path: Optional[str] = None
_flush_interval: int = 300  # 5 min


def start_periodic_flush(path: str, interval_sec: int = 300) -> None:
    """`path` に `interval_sec` ごとに snapshot をダンプする scheduler を起動。
    すでに走っていれば何もしない。"""
    global _flush_timer, _flush_path, _flush_interval
    if _flush_timer is not None:
        return
    _flush_path = path
    _flush_interval = max(60, int(interval_sec))
    _schedule_next()


def _schedule_next() -> None:
    global _flush_timer
    _flush_timer = threading.Timer(_flush_interval, _do_flush)
    _flush_timer.daemon = True
    _flush_timer.start()


def _do_flush() -> None:
    try:
        if _flush_path:
            flush_to_file(_flush_path)
    except Exception:
        pass
    _schedule_next()
