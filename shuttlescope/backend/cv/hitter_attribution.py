"""Track C4: Hitter Attribution 3 段階フォールバック。

各ストロークで「誰が打ったか」を以下の優先順で決定する:

  Priority 1 (HIGH):    SwingDetector が SwingEvent を返した player
                        → SwingEvent.identity を採用、source='swing_detector'
  Priority 2 (MEDIUM):  SwingEvent なし。shuttle 位置に最も近い player
                        → cv_aligner / candidate_builder の従来ロジック流用、
                           source='proximity'
  Priority 3 (LOW):     どちらも失敗。review_required フラグを立てる
                        → reason='no_swing_no_shuttle'

データ出力:
  HitterAttribution: identity / source / confidence / fallback_reasons
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, List, Literal, Optional

from backend.cv.swing_detector import SwingEvent

HitterSource = Literal["swing_detector", "proximity", "review_required"]


@dataclass
class HitterAttribution:
    """1 ストロークに対する hitter 推定結果。"""
    identity: Optional[str]
    source: HitterSource
    confidence: float
    fallback_reasons: List[str] = field(default_factory=list)


def attribute_hitter(
    *,
    stroke_timestamp_sec: float,
    swing_events: Iterable[SwingEvent],
    shuttle_position: Optional[tuple] = None,            # (x_norm, y_norm) at stroke ts
    player_positions: Optional[List[dict]] = None,        # [{"label", "centroid": [x,y]}, ...]
    swing_window_sec: float = 0.25,
    proximity_max_dist: float = 0.35,
) -> HitterAttribution:
    """3 段階で hitter を推定する。

    Args:
        stroke_timestamp_sec: ストロークのタイムスタンプ (秒)
        swing_events: 当該ラリー内で検出された SwingEvent のリスト
        shuttle_position: 該当時刻の shuttle 位置 (画像正規化、None なら proximity 不可)
        player_positions: 該当時刻周辺のプレイヤー検出
        swing_window_sec: stroke ts ± この秒数の SwingEvent を Priority 1 候補にする
        proximity_max_dist: shuttle ↔ player の最大許容距離 (画像正規化)

    Returns:
        HitterAttribution
    """
    # Priority 1: SwingEvent
    candidates = [
        ev for ev in swing_events
        if abs(ev.timestamp_sec - stroke_timestamp_sec) <= swing_window_sec
    ]
    if candidates:
        winner = max(candidates, key=lambda e: e.confidence)
        return HitterAttribution(
            identity=winner.identity,
            source="swing_detector",
            confidence=winner.confidence,
        )

    fallback_reasons: List[str] = ["no_swing_in_window"]

    # Priority 2: proximity to shuttle
    if shuttle_position and player_positions:
        sx, sy = shuttle_position
        nearest_label: Optional[str] = None
        nearest_dist: float = float("inf")
        for p in player_positions:
            label = p.get("label")
            c = p.get("centroid")
            if not label or not c or len(c) < 2:
                continue
            dx = c[0] - sx
            dy = c[1] - sy
            d = math.sqrt(dx * dx + dy * dy)
            if d < nearest_dist:
                nearest_dist = d
                nearest_label = label
        if nearest_label is not None and nearest_dist <= proximity_max_dist:
            # 距離 0 → confidence 1.0、距離 max → 0
            conf = max(0.0, 1.0 - nearest_dist / proximity_max_dist)
            return HitterAttribution(
                identity=nearest_label,
                source="proximity",
                confidence=round(conf, 3),
                fallback_reasons=fallback_reasons,
            )
        fallback_reasons.append("no_player_near_shuttle")
    else:
        if not shuttle_position:
            fallback_reasons.append("no_shuttle_position")
        if not player_positions:
            fallback_reasons.append("no_player_positions")

    # Priority 3: review_required
    return HitterAttribution(
        identity=None,
        source="review_required",
        confidence=0.0,
        fallback_reasons=fallback_reasons,
    )
