"""コート座標マッパー

YOLO 検出結果（正規化画像座標）をコート相対座標・フォーメーション情報に変換する。

コート座標系:
  x: 0.0 (左端) → 1.0 (右端)
  y: 0.0 (上端 / ネット寄り) → 1.0 (下端 / ベースライン寄り)

バドミントンコートでは画像上部と下部に各チームが配置されるため、
y 軸が実際のコート奥行きに相当することが多い。
"""
from __future__ import annotations

import math
from typing import Optional

# ─── しきい値 ────────────────────────────────────────────────────────────────

COURT_MID_X: float = 0.5        # 左右分割
DEPTH_FRONT_Y: float = 0.35     # ネット側（y < DEPTH_FRONT_Y）
DEPTH_BACK_Y: float = 0.65      # ベースライン側（y > DEPTH_BACK_Y）

FORMATION_MIN_Y_DIFF: float = 0.18   # 前衛/後衛と判定するための最小 y 差
FORMATION_MIN_X_DIFF: float = 0.25   # 平行陣と判定するための最小 x 差

PLAYER_LABELS = {"player_a", "player_b"}


# ─── フォーメーション分類 ─────────────────────────────────────────────────────

def classify_formation(players: list[dict]) -> str:
    """2 人のプレイヤー検出からフォーメーションを分類する。

    Returns:
        "front_back"  — 前衛/後衛の縦陣
        "parallel"    — 横並び平行陣
        "mixed"       — 中間的
        "unknown"     — プレイヤーが 2 人未満
    """
    p_a = _get_player(players, "player_a")
    p_b = _get_player(players, "player_b")
    if p_a is None or p_b is None:
        return "unknown"

    cx_a, cy_a = p_a["centroid"]
    cx_b, cy_b = p_b["centroid"]
    y_diff = abs(cy_a - cy_b)
    x_diff = abs(cx_a - cx_b)

    if y_diff >= FORMATION_MIN_Y_DIFF and y_diff > x_diff:
        return "front_back"
    if x_diff >= FORMATION_MIN_X_DIFF and x_diff >= y_diff:
        return "parallel"
    return "mixed"


# ─── 最近傍プレイヤー ─────────────────────────────────────────────────────────

def nearest_player_to_point(
    players: list[dict], x_norm: float, y_norm: float
) -> Optional[dict]:
    """指定した正規化座標に最も近いプレイヤー検出を返す。"""
    candidates = [p for p in players if p.get("label") in PLAYER_LABELS]
    if not candidates:
        return None
    return min(candidates, key=lambda p: _dist2(p["centroid"], x_norm, y_norm))


def _dist2(centroid: list[float], x: float, y: float) -> float:
    return math.sqrt((centroid[0] - x) ** 2 + (centroid[1] - y) ** 2)


def _get_player(players: list[dict], label: str) -> Optional[dict]:
    return next((p for p in players if p.get("label") == label), None)


# ─── フレーム群の集計 ─────────────────────────────────────────────────────────

def summarize_frame_positions(frames_data: list[dict]) -> dict:
    """フレーム群のプレイヤー位置情報を集計してサマリーを返す。

    Args:
        frames_data: [{"frame_idx": int, "timestamp_sec": float, "players": [...]}]

    Returns:
        {
          "total_frames": int,
          "frames_with_both_players": int,
          "formations": {"front_back": int, "parallel": int, "mixed": int, "unknown": int},
          "front_back_ratio": float,
          "parallel_ratio": float,
          "player_a_avg_position": [x, y] | None,
          "player_b_avg_position": [x, y] | None,
          "player_a_depth_band": {"front": int, "mid": int, "back": int},
          "player_b_depth_band": {"front": int, "mid": int, "back": int},
          "player_a_court_side": {"left": int, "right": int},
          "player_b_court_side": {"left": int, "right": int},
        }
    """
    total = len(frames_data)
    formation_counts: dict[str, int] = {
        "front_back": 0, "parallel": 0, "mixed": 0, "unknown": 0
    }
    frames_both = 0

    pos_a: list[list[float]] = []
    pos_b: list[list[float]] = []
    depth_a: dict[str, int] = {"front": 0, "mid": 0, "back": 0}
    depth_b: dict[str, int] = {"front": 0, "mid": 0, "back": 0}
    side_a: dict[str, int] = {"left": 0, "right": 0}
    side_b: dict[str, int] = {"left": 0, "right": 0}

    for frame in frames_data:
        players = frame.get("players", [])
        fm = classify_formation(players)
        formation_counts[fm] = formation_counts.get(fm, 0) + 1

        has_a = has_b = False
        for p in players:
            lbl = p.get("label")
            c = p.get("centroid", [])
            if not c or len(c) < 2:
                continue
            if lbl == "player_a":
                pos_a.append(c)
                depth_a[p.get("depth_band", "mid")] = depth_a.get(p.get("depth_band", "mid"), 0) + 1
                side_a[p.get("court_side", "left")] = side_a.get(p.get("court_side", "left"), 0) + 1
                has_a = True
            elif lbl == "player_b":
                pos_b.append(c)
                depth_b[p.get("depth_band", "mid")] = depth_b.get(p.get("depth_band", "mid"), 0) + 1
                side_b[p.get("court_side", "right")] = side_b.get(p.get("court_side", "right"), 0) + 1
                has_b = True

        if has_a and has_b:
            frames_both += 1

    def avg(positions: list[list[float]]) -> Optional[list[float]]:
        if not positions:
            return None
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        return [round(sum(xs) / len(xs), 4), round(sum(ys) / len(ys), 4)]

    return {
        "total_frames": total,
        "frames_with_both_players": frames_both,
        "formations": formation_counts,
        "front_back_ratio": round(formation_counts["front_back"] / max(total, 1), 3),
        "parallel_ratio": round(formation_counts["parallel"] / max(total, 1), 3),
        "player_a_avg_position": avg(pos_a),
        "player_b_avg_position": avg(pos_b),
        "player_a_frame_count": len(pos_a),
        "player_b_frame_count": len(pos_b),
        "player_a_depth_band": depth_a,
        "player_b_depth_band": depth_b,
        "player_a_court_side": side_a,
        "player_b_court_side": side_b,
    }


# ─── ラリー区間サマリー ────────────────────────────────────────────────────────

def summarize_rally_positions(
    frames_data: list[dict],
    rally_start_sec: float,
    rally_end_sec: float,
) -> dict:
    """ラリー時間帯のフレームのみを対象に集計する。"""
    rally_frames = [
        f for f in frames_data
        if rally_start_sec <= f.get("timestamp_sec", 0) <= rally_end_sec
    ]
    return summarize_frame_positions(rally_frames)
