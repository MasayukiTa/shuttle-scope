"""YOLO + TrackNet アライメントエンジン

フレームタイムスタンプをキーに YOLO プレイヤー検出と TrackNet シャトル軌跡を統合し、
ラリー単位でのヒッター候補・受け圧力コンテキストを生成する。

出力（per-rally alignment）:
  {
    "rally_id": int,
    "start_sec": float,
    "end_sec": float,
    "events": [
      {
        "timestamp_sec": float,
        "shuttle": {"x_norm": float, "y_norm": float, "zone": str, "confidence": float},
        "players": [...],                        # YOLO 検出
        "hitter_candidate": "player_a" | "player_b" | None,
        "hitter_distance": float,                # シャトルと最近傍プレイヤーの距離
        "receiver_candidate": "player_a" | "player_b" | None,
        "formation": str,
      },
      ...
    ],
    "summary": {
      "hitter_a_count": int,    # player_a がヒッター候補だった回数
      "hitter_b_count": int,
      "dominant_formation": str,
    }
  }
"""
from __future__ import annotations

import bisect
import logging
from typing import Optional

from backend.yolo.court_mapper import nearest_player_to_point, classify_formation

logger = logging.getLogger(__name__)

# YOLO フレームとシャトルフレームのタイムスタンプ許容マッチング幅（秒）
MATCH_WINDOW_SEC: float = 0.5

# ヒッター候補とみなすための最大シャトル距離（正規化コード座標）
MAX_HITTER_DIST: float = 0.35

# ラリー境界のパディング（秒）: 映像同期ずれを吸収
RALLY_BOUNDARY_PAD_SEC: float = 0.25


def align_match(
    yolo_frames: list[dict],
    tracknet_frames: list[dict],
    rallies: list[dict],
) -> list[dict]:
    """試合全体の YOLO + TrackNet アライメントを計算する。

    Args:
        yolo_frames: [{"frame_idx": int, "timestamp_sec": float, "players": [...]}]
        tracknet_frames: [{"timestamp_sec": float, "zone": str|None,
                           "confidence": float, "x_norm": float|None, "y_norm": float|None}]
        rallies: [{"rally_id": int, "start_sec": float, "end_sec": float}]

    Returns:
        per-rally alignment list
    """
    # タイムスタンプ→インデックスのルックアップを事前構築
    yolo_ts = [f["timestamp_sec"] for f in yolo_frames]
    tracknet_ts = [f["timestamp_sec"] for f in tracknet_frames]

    results: list[dict] = []
    for rally in rallies:
        rally_id = rally.get("rally_id", 0)
        start_sec = rally.get("start_sec", 0.0)
        end_sec = rally.get("end_sec", start_sec + 5.0)

        # ラリー境界パディング: 映像タイムスタンプのずれを吸収
        padded_start = max(0.0, start_sec - RALLY_BOUNDARY_PAD_SEC)
        padded_end = end_sec + RALLY_BOUNDARY_PAD_SEC

        rally_yolo = _frames_in_range(yolo_frames, yolo_ts, padded_start, padded_end)
        rally_tracknet = _frames_in_range(tracknet_frames, tracknet_ts, padded_start, padded_end)

        events = _build_events(rally_yolo, rally_tracknet)
        summary = _summarize_events(events)

        results.append({
            "rally_id": rally_id,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "events": events,
            "summary": summary,
        })

    return results


def _frames_in_range(frames: list[dict], timestamps: list[float],
                     start: float, end: float) -> list[dict]:
    lo = bisect.bisect_left(timestamps, start)
    hi = bisect.bisect_right(timestamps, end)
    return frames[lo:hi]


def _build_events(
    yolo_frames: list[dict],
    tracknet_frames: list[dict],
) -> list[dict]:
    """各 TrackNet フレームに最近傍 YOLO フレームをマッチングしてイベントを構築する。"""
    yolo_ts = [f["timestamp_sec"] for f in yolo_frames]
    events: list[dict] = []

    for tf in tracknet_frames:
        ts = tf.get("timestamp_sec", 0.0)
        shuttle_x = tf.get("x_norm")
        shuttle_y = tf.get("y_norm")
        shuttle_zone = tf.get("zone")
        shuttle_conf = tf.get("confidence", 0.0)

        # 最近傍 YOLO フレームを取得
        players: list[dict] = []
        if yolo_ts:
            idx = bisect.bisect_left(yolo_ts, ts)
            # 直前・直後の候補を比較
            best_idx = None
            best_gap = float("inf")
            for i in [idx - 1, idx]:
                if 0 <= i < len(yolo_ts):
                    gap = abs(yolo_ts[i] - ts)
                    if gap < best_gap and gap <= MATCH_WINDOW_SEC:
                        best_gap = gap
                        best_idx = i
            if best_idx is not None:
                players = yolo_frames[best_idx].get("players", [])

        formation = classify_formation(players)

        # ヒッター候補: シャトル位置に最近傍のプレイヤー
        hitter: Optional[str] = None
        hitter_dist: float = 0.0
        hitter_confidence: float = 0.0  # 距離から算出した候補確信度（0-1）
        if shuttle_x is not None and shuttle_y is not None and shuttle_conf >= 0.4:
            nearest = nearest_player_to_point(players, shuttle_x, shuttle_y)
            if nearest:
                cx, cy = nearest["centroid"]
                import math
                hitter_dist = round(math.sqrt(
                    (cx - shuttle_x) ** 2 + (cy - shuttle_y) ** 2
                ), 4)
                if hitter_dist <= MAX_HITTER_DIST:
                    hitter = nearest.get("label")
                    # 距離が近いほど確信度が高い（線形減衰）
                    hitter_confidence = round(
                        (1.0 - hitter_dist / MAX_HITTER_DIST) * shuttle_conf, 3
                    )

        # 受け手候補: ヒッターでない方
        receiver: Optional[str] = None
        if hitter == "player_a":
            receiver = "player_b"
        elif hitter == "player_b":
            receiver = "player_a"

        events.append({
            "timestamp_sec": round(ts, 3),
            "shuttle": {
                "x_norm": shuttle_x,
                "y_norm": shuttle_y,
                "zone": shuttle_zone,
                "confidence": shuttle_conf,
            },
            "players": players,
            # hitter_candidate: CV 推定。最終的な真値ではない（annotation truth への書き込み不可）
            "hitter_candidate": hitter,
            "hitter_distance": hitter_dist,
            "hitter_confidence": hitter_confidence,
            "receiver_candidate": receiver,
            "formation": formation,
        })

    return events


def _summarize_events(events: list[dict]) -> dict:
    hitter_a = sum(1 for e in events if e.get("hitter_candidate") == "player_a")
    hitter_b = sum(1 for e in events if e.get("hitter_candidate") == "player_b")
    formations: dict[str, int] = {}
    conf_a_sum = 0.0
    conf_b_sum = 0.0
    for e in events:
        fm = e.get("formation", "unknown")
        formations[fm] = formations.get(fm, 0) + 1
        hc = e.get("hitter_candidate")
        hconf = e.get("hitter_confidence", 0.0)
        if hc == "player_a":
            conf_a_sum += hconf
        elif hc == "player_b":
            conf_b_sum += hconf

    dominant_formation = max(formations, key=formations.get) if formations else "unknown"
    total_hitter_events = max(hitter_a + hitter_b, 1)

    return {
        "hitter_a_count": hitter_a,
        "hitter_b_count": hitter_b,
        # 候補確信度平均（0 = 不明、1 = 非常に近い）
        "hitter_a_avg_confidence": round(conf_a_sum / max(hitter_a, 1), 3),
        "hitter_b_avg_confidence": round(conf_b_sum / max(hitter_b, 1), 3),
        "dominant_formation": dominant_formation,
        "formation_counts": formations,
        # hitter_candidate は CV 推定値。annotation truth への直接適用は不可
        "note": "candidate — CV assisted, not ground truth",
    }
