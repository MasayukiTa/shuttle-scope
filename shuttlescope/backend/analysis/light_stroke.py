"""light_stroke.py — ORM materialize を避ける軽量 Stroke ローダー。

背景 (SD-09b 504 調査, 実測):
  個別解析エンドポイント (epv / epv_state_table / state_action_values 他) は、
  1 リクエストあたり約 2.9 万件の Stroke を full ORM で materialize しており、
  cProfile 上 sqlalchemy.orm.loading._populate_full が 30,782 回・約 2.6s を占める
  (SQL は 5 本のみ。N+1 ではなく ORM インスタンス化そのものがボトルネック)。

  計測 (_sd09b_profile.db, 28,927 strokes):
    full ORM            : 3.5〜4.9s
    load_only(列限定)   : 3.4s (ほぼ無効 — 1 インスタンスの生成コストが本体)
    Core tuple select   : 0.36s
    Core + __slots__ wrap: 1.9s

  Core select で列だけ取得し、属性アクセス互換の __slots__ オブジェクトに詰める。
  compute_rally_state_epv / compute_q_values の出力は full ORM と完全一致することを
  scripts/sd09b_lightstroke_micro.py で確認済み (identical=True)。

pending sentinel 除外は pending_strokes と同じ条件を Core 側でも適用する (fail closed)。
"""
from __future__ import annotations

from sqlalchemy import not_, or_

from backend.db.models import Stroke
from backend.analysis.pending_strokes import (
    PENDING_FINAL_SHOT_TYPE,
    PENDING_FINAL_STROKE_NUM,
)

# 解析カード群が参照する Stroke 列 (grep 実測ベース + 座標系/ゾーン系を網羅)。
# 列を増やしても Core select のコストはほぼ変わらない (ORM 生成を避けるのが本質)。
LIGHT_STROKE_FIELDS = (
    "id", "rally_id", "stroke_num", "player", "shot_type", "shot_quality",
    "hit_zone", "hit_zone_source", "land_zone", "land_zone_source",
    "hit_x", "hit_y", "land_x", "land_y",
    "player_x", "player_y", "opponent_x", "opponent_y",
    "opponent_contact_x", "opponent_contact_y",
    "player_contact_x", "player_contact_y",
    "return_target_x", "return_target_y",
)


class LightStroke:
    """full ORM Stroke の読み取り互換な軽量オブジェクト (__slots__)。"""

    __slots__ = LIGHT_STROKE_FIELDS

    def __init__(self, row):
        for f in LIGHT_STROKE_FIELDS:
            setattr(self, f, getattr(row, f))


def load_light_strokes(db, rally_ids: list[int]) -> list[LightStroke]:
    """rally_ids に属する非 pending ストロークを軽量オブジェクトとして返す。

    full ORM の db.query(Stroke)...all() と同じ行集合 (pending sentinel 除外) を
    返すが、ORM インスタンス化を回避して約 2〜10 倍速い。
    """
    if not rally_ids:
        return []
    cols = [getattr(Stroke, f) for f in LIGHT_STROKE_FIELDS]
    rows = (
        db.query(*cols)
        .filter(Stroke.rally_id.in_(rally_ids))
        .filter(
            not_(
                or_(
                    Stroke.stroke_num == PENDING_FINAL_STROKE_NUM,
                    Stroke.shot_type == PENDING_FINAL_SHOT_TYPE,
                )
            )
        )
        .all()
    )
    return [LightStroke(r) for r in rows]


__all__ = ["LightStroke", "LIGHT_STROKE_FIELDS", "load_light_strokes"]
