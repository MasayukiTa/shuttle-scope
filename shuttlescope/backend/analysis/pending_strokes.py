"""pending_strokes.py — Pass 2/3 の未確定 sentinel stroke を扱う共通ヘルパー。

Pass 2 は最終打を stroke_num=9999 / shot_type='__final_pending' の placeholder として
enqueue する。Pass 3 完了時に通常番号へ再採番されるが、確定前の行が
解析・統計クエリへ流れると、ショット系列・ラリー長・最終打分類を壊す。
このモジュールは sentinel の定数と、query / in-memory list 両方で pending を
除外する共通関数を提供する。fail closed: stroke_num もしくは shot_type の
どちらかが sentinel なら pending とみなして除外する。
"""
from __future__ import annotations

from sqlalchemy import and_, not_, or_

from backend.db.models import Stroke

# Pass 2 が最終打を確保する sentinel 値 (Pass2ServeFinal.tsx / strokes.py と一致)
PENDING_FINAL_STROKE_NUM = 9999
PENDING_FINAL_SHOT_TYPE = "__final_pending"


def is_pending_stroke(stroke) -> bool:
    """in-memory の Stroke が未確定 sentinel かどうか (fail closed: OR 判定)。"""
    return (
        getattr(stroke, "stroke_num", None) == PENDING_FINAL_STROKE_NUM
        or getattr(stroke, "shot_type", None) == PENDING_FINAL_SHOT_TYPE
    )


def exclude_pending_strokes(query):
    """db.query(Stroke) に pending sentinel 除外フィルタを追加して返す。

    stroke_num==9999 または shot_type=='__final_pending' のどちらかを満たす行を
    解析・統計から落とす (fail closed)。
    """
    return query.filter(
        not_(
            or_(
                Stroke.stroke_num == PENDING_FINAL_STROKE_NUM,
                Stroke.shot_type == PENDING_FINAL_SHOT_TYPE,
            )
        )
    )


def filter_non_pending(strokes):
    """in-memory list から pending sentinel を除外した新しい list を返す。"""
    return [s for s in strokes if not is_pending_stroke(s)]


__all__ = [
    "PENDING_FINAL_STROKE_NUM",
    "PENDING_FINAL_SHOT_TYPE",
    "is_pending_stroke",
    "exclude_pending_strokes",
    "filter_non_pending",
]
