"""重心・バランス派生値の計算（GPU 不要・数値式のみ）。

Pose 推定のランドマークから左右荷重比 / 前後傾き / 安定度を算出する。
CUDA/torch は import しないこと。
"""
from __future__ import annotations

from typing import Iterable, Sequence


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, v))


def compute_cog(landmarks: Sequence[Sequence[float]]) -> dict:
    """単一フレームの重心指標を計算する。

    Args:
        landmarks: [(x, y, visibility), ...] 形式のランドマーク列。
                   最低限、左右足首と骨盤中心相当が含まれる想定。
    Returns:
        {left_pct, right_pct, forward_lean, stability_score}
    """
    if not landmarks:
        return {"left_pct": 0.5, "right_pct": 0.5, "forward_lean": 0.0, "stability_score": 0.0}

    def _xy(p):
        if isinstance(p, dict):
            return p.get("x"), p.get("y")
        if p and len(p) >= 2:
            return p[0], p[1]
        return None, None

    pts = [_xy(p) for p in landmarks]
    xs = [x for x, _y in pts if x is not None]
    ys = [y for _x, y in pts if y is not None]
    if not xs:
        return {"left_pct": 0.5, "right_pct": 0.5, "forward_lean": 0.0, "stability_score": 0.0}

    # 左右荷重: 足首相当（最後の 2 点）で近似
    left_x_pair = _xy(landmarks[-2]) if len(landmarks) >= 2 else (xs[0], None)
    right_x_pair = _xy(landmarks[-1]) if len(landmarks) >= 1 else (xs[-1], None)
    left_x = left_x_pair[0] if left_x_pair[0] is not None else xs[0]
    right_x = right_x_pair[0] if right_x_pair[0] is not None else xs[-1]
    center_x = (left_x + right_x) / 2.0
    com_x = sum(xs) / len(xs)
    # com が中心より左にあれば左荷重
    delta = com_x - center_x
    span = max(abs(right_x - left_x), 1e-6)
    left_pct = _clip01(0.5 - delta / span)
    right_pct = 1.0 - left_pct

    # 前傾: 肩 (top) と腰 (mid) の y 差で近似
    com_y = sum(ys) / len(ys)
    forward_lean = float(ys[0] - com_y) if ys else 0.0

    # 安定度: ランドマーク分散の逆数（正規化）
    var_x = sum((x - com_x) ** 2 for x in xs) / max(len(xs), 1)
    stability = _clip01(1.0 / (1.0 + var_x * 10.0))

    return {
        "left_pct": float(left_pct),
        "right_pct": float(right_pct),
        "forward_lean": float(forward_lean),
        "stability_score": float(stability),
    }


def compute_cog_batch(frames: Iterable[Sequence[Sequence[float]]]) -> list[dict]:
    """フレーム列に対して重心を計算する。"""
    return [compute_cog(lm) for lm in frames]
