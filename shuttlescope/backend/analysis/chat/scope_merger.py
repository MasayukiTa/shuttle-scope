"""Conversational scope merger.

last-write-wins per slot. ユーザが明示クリア (リセット / 全部 / reset 等) した場合は
スロット個別 or 全体クリアを行う。
"""
from __future__ import annotations

from typing import Optional


_SLOTS = ("period", "shot_type", "zone")


def _empty_scope() -> dict:
    return {
        "period": None,
        "shot_type": None,
        "zone": None,
        "updated_turn": 0,
        "history": [],
    }


def _normalize(prev: Optional[dict]) -> dict:
    if not isinstance(prev, dict):
        return _empty_scope()
    out = _empty_scope()
    for s in _SLOTS:
        v = prev.get(s)
        out[s] = v if isinstance(v, dict) else None
    out["updated_turn"] = int(prev.get("updated_turn", 0) or 0)
    hist = prev.get("history") or []
    out["history"] = list(hist) if isinstance(hist, list) else []
    return out


def merge_scope(
    prev: Optional[dict],
    deltas: dict,
    turn: int,
    source: str = "extracted",
) -> dict:
    """前回スコープに新ターンの delta をマージ。

    deltas keys: period / shot_type / zone (None or dict), 任意で
      - clear_all_scope: True → 全クリア (history は保持)
      - clear_slots: list[str] → 個別スロットクリア
    """
    cur = _normalize(prev)

    if deltas.get("clear_all_scope"):
        cleared = _empty_scope()
        cleared["updated_turn"] = turn
        cleared["history"] = cur["history"] + [
            {"turn": turn, "slot": "__all__", "value": None, "source": source}
        ]
        return cleared

    for s in deltas.get("clear_slots") or []:
        if s in _SLOTS and cur.get(s) is not None:
            cur[s] = None
            cur["history"].append(
                {"turn": turn, "slot": s, "value": None, "source": source}
            )

    for s in _SLOTS:
        v = deltas.get(s)
        if v is None:
            continue
        if not isinstance(v, dict):
            continue
        cur[s] = v
        cur["history"].append(
            {"turn": turn, "slot": s, "value": v, "source": source}
        )

    cur["updated_turn"] = turn
    # history を長すぎないように clip
    if len(cur["history"]) > 100:
        cur["history"] = cur["history"][-100:]
    return cur


# ─── clear signal detection ──────────────────────────────────────
_CLEAR_ALL_PATTERNS = [
    "リセット",
    "全部リセット",
    "全部クリア",
    "reset filters",
    "reset all",
    "clear all",
]
_CLEAR_PERIOD_PATTERNS = ["全期間", "全部の期間", "全部の期間で", "all time", "all-time"]
_CLEAR_SHOT_PATTERNS = ["全ショット", "全種類", "all shots"]
_CLEAR_ZONE_PATTERNS = ["全エリア", "全ゾーン", "all zones", "全コート"]


def clear_signals(text: str) -> set[str]:
    """テキストから明示クリア対象スロットを判定する。

    返値: クリア対象スロット名 set。"__all__" を含む場合は全クリア。
    """
    if not text:
        return set()
    out: set[str] = set()
    low = text.lower()
    for p in _CLEAR_ALL_PATTERNS:
        if p.lower() in low:
            out.add("__all__")
            break
    for p in _CLEAR_PERIOD_PATTERNS:
        if p.lower() in low:
            out.add("period")
    for p in _CLEAR_SHOT_PATTERNS:
        if p.lower() in low:
            out.add("shot_type")
    for p in _CLEAR_ZONE_PATTERNS:
        if p.lower() in low:
            out.add("zone")
    return out
