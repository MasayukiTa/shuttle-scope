"""監査ログ画面向けの純粋な整形・集約ヘルパ (DB に触れない)。

- 監視画面自身の読み取りを request_logs から除く判定
- エラーメッセージの要約 (生 SQL / parameters / ライブラリの案内リンクを除く)
- 同じ原因のエラー・同じ発信元の連続イベントを 1 行に束ねる集約
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Iterable, Optional

# 監視画面が履歴を読むために叩く API の共通 prefix。
MONITORING_READ_PREFIX = "/api/auth/audit-logs"


def is_monitoring_self_read(method: Optional[str], path: Optional[str], status: Optional[int]) -> bool:
    """監視画面自身の「成功した GET」か。

    監視画面を開くだけでログが増えると、実トラフィックを調べるときの S/N が落ちる。
    ただし 401/403 などの失敗は、権限のない者が監視 API を探った記録として残す。
    """
    if (method or "").upper() != "GET":
        return False
    if not (path or "").startswith(MONITORING_READ_PREFIX):
        return False
    if status is None:
        return False
    return int(status) < 400


# 生 SQL / パラメータ / ライブラリの案内リンクの開始位置。ここから後ろは要約に含めない。
_NOISE_MARKERS = ("[SQL:", "[parameters:", "(Background on this error")


def summarize_error_message(message: Optional[str], max_len: int = 200) -> Optional[str]:
    """エラー文の主表示用要約。空なら None。

    SQLAlchemy の例外は「原因 / [SQL: ...] / [parameters: ...] / (Background ...)」の
    形をしている。原因の部分だけを残し、先頭 1 行に切り詰める。
    """
    if not message:
        return None
    text = str(message)
    cut = len(text)
    for marker in _NOISE_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    text = text[:cut]
    first = ""
    for line in text.splitlines():
        if line.strip():
            first = line.strip()
            break
    if not first:
        return None
    if len(first) > max_len:
        first = first[: max_len - 1] + "…"
    return first


_ID_SEGMENT = re.compile(r"/\d+(?=/|$)")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_NUMBER = re.compile(r"\d+")


def error_fingerprint(
    exc_type: Optional[str],
    method: Optional[str],
    path: Optional[str],
    message: Optional[str],
) -> str:
    """同じ原因のエラーを同じ値にする指紋 (16 桁の hex)。

    パスの数値 id、メッセージ中の数値と UUID は発生ごとに変わるため畳んでから比べる。
    """
    norm_path = _ID_SEGMENT.sub("/:id", path or "")
    summary = summarize_error_message(message) or ""
    summary = _UUID.sub("<uuid>", summary)
    summary = _NUMBER.sub("#", summary)
    raw = "|".join([exc_type or "", (method or "").upper(), norm_path, summary])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]  # noqa: S324 - 識別用で暗号用途ではない


def group_error_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """新しい順の error_logs 行を指紋ごとにまとめる。

    各グループ: 初回/最終発生・回数・要約・直近の request_id。
    入力は新しい順 (id 降順)。戻りも最終発生が新しい順。
    "解決済み" かどうかを持つ列は無いので、ここでは判定しない。
    """
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for r in rows:
        fp = error_fingerprint(r.get("exc_type"), r.get("method"), r.get("path"), r.get("message"))
        ts = r.get("ts")
        g = groups.get(fp)
        if g is None:
            g = {
                "fingerprint": fp,
                "exc_type": r.get("exc_type"),
                "method": r.get("method"),
                "path": r.get("path"),
                "status": r.get("status"),
                "summary": summarize_error_message(r.get("message")),
                "count": 0,
                "first_ts": ts,
                "last_ts": ts,
                "last_id": r.get("id"),
                "last_request_id": r.get("request_id"),
            }
            groups[fp] = g
            order.append(fp)
        g["count"] += 1
        if isinstance(ts, datetime):
            if not isinstance(g["first_ts"], datetime) or ts < g["first_ts"]:
                g["first_ts"] = ts
            if not isinstance(g["last_ts"], datetime) or ts > g["last_ts"]:
                g["last_ts"] = ts
    result = [groups[fp] for fp in order]
    result.sort(key=lambda g: g["last_ts"] if isinstance(g["last_ts"], datetime) else datetime.min, reverse=True)
    return result


_SEVERITY_RANK = {"info": 0, "warn": 1, "critical": 2}
_SAMPLE_PATHS = 5


def group_security_rows(rows: Iterable[dict[str, Any]], gap_seconds: int = 300) -> list[dict[str, Any]]:
    """新しい順の security_events 行を (ip, event_type) の連続したまとまりに束ねる。

    同じ ip と event_type の行で、隣り合う発生の間隔が gap_seconds 以内なら 1 つに束ねる
    (1 回のスキャンが数十行を占めないようにする)。展開用に、パスの種類数と先頭数件を返す。
    入力は新しい順。戻りは最終発生が新しい順。
    """
    open_groups: dict[tuple[Any, Any], dict[str, Any]] = {}
    result: list[dict[str, Any]] = []
    for r in rows:
        key = (r.get("ip_addr"), r.get("event_type"))
        ts = r.get("ts")
        g = open_groups.get(key)
        if g is not None and isinstance(ts, datetime) and isinstance(g["first_ts"], datetime):
            if (g["first_ts"] - ts).total_seconds() > gap_seconds:
                g = None
        if g is None:
            g = {
                "ip_addr": r.get("ip_addr"),
                "event_type": r.get("event_type"),
                "severity": r.get("severity"),
                "count": 0,
                "first_ts": ts,
                "last_ts": ts,
                "last_id": r.get("id"),
                "distinct_paths": 0,
                "sample_paths": [],
                "_paths": set(),
            }
            open_groups[key] = g
            result.append(g)
        g["count"] += 1
        if isinstance(ts, datetime):
            g["first_ts"] = ts
        sev = r.get("severity")
        if _SEVERITY_RANK.get(sev or "", -1) > _SEVERITY_RANK.get(g["severity"] or "", -1):
            g["severity"] = sev
        p = r.get("path")
        if p and p not in g["_paths"]:
            g["_paths"].add(p)
            if len(g["sample_paths"]) < _SAMPLE_PATHS:
                g["sample_paths"].append(p)
    for g in result:
        g["distinct_paths"] = len(g.pop("_paths"))
    return result
