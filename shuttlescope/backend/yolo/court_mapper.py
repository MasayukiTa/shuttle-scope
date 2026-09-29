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

def _floor_point(player: dict) -> Optional[tuple[float, float]]:
    """人物 bbox の床面近似点を返す。centroid は床面点ではないので代用しない。"""
    point = player.get("foot_point")
    if not point or len(point) < 2:
        return None
    try:
        return (float(point[0]), float(point[1]))
    except (TypeError, ValueError):
        return None


def classify_formation(players: list[dict], court_adapter=None) -> str:
    """2 人のプレイヤー検出からフォーメーションを分類する。

    キャリブレーション済みでは人物の foot_point（床面近似点）を homography
    でコート座標へ写像して判定する。bbox centroid は空中の点なので、床 homography
    へ入れない。未校正時の画像座標分類は legacy/debug 互換としてのみ残す。

    Returns:
        "front_back"  — 前衛/後衛の縦陣
        "parallel"    — 横並び平行陣
        "mixed"       — 中間的
        "unknown"     — プレイヤーが 2 人未満 / 床面点が無い
    """
    p_a = _get_player(players, "player_a")
    p_b = _get_player(players, "player_b")
    if p_a is None or p_b is None:
        return "unknown"

    if court_adapter is not None and getattr(court_adapter, "is_calibrated", False):
        point_a = _floor_point(p_a)
        point_b = _floor_point(p_b)
        if point_a is None or point_b is None:
            return "unknown"
        return court_adapter.formation_type(point_a, point_b)

    centroid_a = p_a.get("centroid")
    centroid_b = p_b.get("centroid")
    if not centroid_a or not centroid_b or len(centroid_a) < 2 or len(centroid_b) < 2:
        return "unknown"
    cx_a, cy_a = centroid_a
    cx_b, cy_b = centroid_b
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

def summarize_frame_positions(frames_data: list[dict], court_adapter=None) -> dict:
    """フレーム群のプレイヤー位置を集計する。

    court_adapter が校正済みのときだけ foot_point を床 homography で
    コート座標へ写像して court-dependent 統計を計算する。未校正時は旧 UI/API
    との後方互換のため画像座標ベースの debug summary を返すが、
    court_calibrated=False / coordinate_space=image_normalized を必ず付ける。
    競技分析側はこの未校正 summary をコート統計として使ってはいけない。
    """
    calibrated = bool(
        court_adapter is not None and getattr(court_adapter, "is_calibrated", False)
    )
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

    def position_for_summary(player: dict) -> Optional[list[float]]:
        if calibrated:
            floor = _floor_point(player)
            if floor is None:
                return None
            try:
                cx, cy = court_adapter.pixel_to_court(*floor)
                if not (math.isfinite(cx) and math.isfinite(cy)):
                    return None
                return [float(cx), float(cy)]
            except (TypeError, ValueError, ZeroDivisionError, FloatingPointError):
                return None

        centroid = player.get("centroid")
        if not centroid or len(centroid) < 2:
            return None
        try:
            return [float(centroid[0]), float(centroid[1])]
        except (TypeError, ValueError):
            return None

    def generic_depth(player: dict) -> str:
        if calibrated:
            floor = _floor_point(player)
            if floor is None:
                return "mid"
            band = str(court_adapter.depth_band(*floor))
            if band.startswith("front"):
                return "front"
            if band.startswith("back"):
                return "back"
            return "mid"
        band = str(player.get("depth_band", "mid"))
        return band if band in {"front", "mid", "back"} else "mid"

    for frame in frames_data:
        players = frame.get("players", [])
        fm = classify_formation(players, court_adapter=court_adapter)
        formation_counts[fm] = formation_counts.get(fm, 0) + 1

        has_a = has_b = False
        for player in players:
            label = player.get("label")
            pos = position_for_summary(player)
            if pos is None:
                continue

            depth = generic_depth(player)
            if calibrated:
                side = "left" if pos[0] < COURT_MID_X else "right"
            else:
                side = str(
                    player.get(
                        "court_side",
                        "left" if pos[0] < COURT_MID_X else "right",
                    )
                )
            if side not in {"left", "right"}:
                side = "left" if pos[0] < COURT_MID_X else "right"

            if label == "player_a":
                pos_a.append(pos)
                depth_a[depth] = depth_a.get(depth, 0) + 1
                side_a[side] = side_a.get(side, 0) + 1
                has_a = True
            elif label == "player_b":
                pos_b.append(pos)
                depth_b[depth] = depth_b.get(depth, 0) + 1
                side_b[side] = side_b.get(side, 0) + 1
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
        "court_calibrated": calibrated,
        "coordinate_space": "court_normalized" if calibrated else "image_normalized",
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
    court_adapter=None,
) -> dict:
    """ラリー時間帯のフレームのみを対象に集計する。"""
    rally_frames = [
        f for f in frames_data
        if rally_start_sec <= f.get("timestamp_sec", 0) <= rally_end_sec
    ]
    return summarize_frame_positions(rally_frames, court_adapter=court_adapter)
