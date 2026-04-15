"""ショット分類（ルールベース・GPU 不要）。

Stroke の既存特徴（shot_type, hit/land zone, is_backhand 等）を基に
軽量ルールでショット種別と確信度を推定する。
将来モデル学習後は model_version を差し替える。
"""
from __future__ import annotations

from typing import Any


MODEL_VERSION = "rule-v0"


def classify_stroke(stroke: Any) -> dict:
    """Stroke ORM or dict を受け取り、shot_type と confidence を返す。"""
    # 既存の shot_type を正とし、軌跡や打点属性から確信度を粗く補正する
    shot_type = getattr(stroke, "shot_type", None) or (
        stroke.get("shot_type") if isinstance(stroke, dict) else None
    ) or "unknown"

    base = 0.6
    # バックハンドや around_head は難度が高く、分類曖昧性が上がる
    is_bh = bool(getattr(stroke, "is_backhand", False) or (
        isinstance(stroke, dict) and stroke.get("is_backhand")
    ))
    if is_bh:
        base -= 0.1
    # hit_zone があるほど確信度が上がる
    hz = getattr(stroke, "hit_zone", None) or (
        stroke.get("hit_zone") if isinstance(stroke, dict) else None
    )
    if hz:
        base += 0.1

    confidence = max(0.05, min(0.99, base))
    return {
        "shot_type": shot_type,
        "confidence": float(confidence),
        "model_version": MODEL_VERSION,
    }
