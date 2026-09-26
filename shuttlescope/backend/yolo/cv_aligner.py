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

# C-8: ラベルが位置ベースの推測だったときの hitter_confidence 上限。
#
# この値は CONF_MEDIUM (既定 0.48) も下回るので、**候補は review_required になる**
# — 自動採用されないだけでなく、人の確認を必ず通る。
# 意図的にそこまで落としている: 2 人が同じ側に立っているとき y 平均での上下割当は
# 実質コイン投げで、「誰が打ったか」を当てている保証が無い。
# 候補自体は残るので、操作者は見て採否を決められる。
#
# より良い形は「2 つの検出が y 方向にどれだけ離れているか」を見て、
# ネットを挟んでいるときだけ割当を信頼することだが、ネット位置
# (court_adapter) が要る。未実装 — private_docs の C-8 参照。
HITTER_GUESS_CONF_CAP = 0.45

# D-5: 位置ベース推測でも、キャリブレーション済みコート上で **2 人だけ**が
# ネットを挟んでいるなら「上/下という幾何ラベル」は coin flip ではない。
# ただし D-3 のシャトル↔人物距離はまだ画像座標なので auto_filled までは上げない。
# 既定 CONF_MEDIUM=0.48 / CONF_HIGH=0.72 の間に固定し、最大 suggested とする。
HITTER_NET_SEPARATED_CONF_CAP = 0.65
_GUESSED_LABEL_SOURCES = {"position_fallback", "overflow"}


def position_label_geometry(
    players: list[dict],
    court_adapter=None,
) -> str:
    """位置ベース player_a/player_b がネット分離で裏付けられるかを分類する。

    player_a/player_b の screen-label を信用できるのは singles 相当の
    2 人だけが検出され、両者の foot_point がキャリブレーション済みコートの
    反対側にある場合だけ。4 人いる doubles、床点欠損、ネット際、未校正では
    推測を昇格しない。
    """
    if court_adapter is None or not getattr(court_adapter, "is_calibrated", False):
        return "uncalibrated"

    court_players = [
        p for p in players
        if p.get("label") in ("player_a", "player_b", "player_c", "player_d")
    ]
    if len(court_players) != 2:
        return "not_two_players"
    by_label = {p.get("label"): p for p in court_players}
    if set(by_label) != {"player_a", "player_b"}:
        return "not_screen_pair"

    sides: dict[str, str] = {}
    for label in ("player_a", "player_b"):
        p = by_label[label]
        foot = p.get("foot_point")
        if not isinstance(foot, (list, tuple)) or len(foot) < 2:
            return "missing_foot_point"
        side = court_adapter.side_of_net(foot[0], foot[1])
        if side is None:
            return "net_ambiguous"
        sides[label] = side

    return "net_separated" if sides["player_a"] != sides["player_b"] else "same_side"


def cap_guessed_hitter_confidence(
    confidence: float,
    nearest_player: Optional[dict],
    players: list[dict],
    court_adapter=None,
) -> tuple[float, Optional[str]]:
    """位置ベース人物ラベルの確信度上限を、ネット幾何で保守的に決める。"""
    if not nearest_player or nearest_player.get("label_source") not in _GUESSED_LABEL_SOURCES:
        return float(confidence), None

    geometry = position_label_geometry(players, court_adapter)
    cap = (
        HITTER_NET_SEPARATED_CONF_CAP
        if geometry == "net_separated"
        else HITTER_GUESS_CONF_CAP
    )
    return min(float(confidence), cap), geometry

# ラリー境界のパディング（秒）: 映像同期ずれを吸収
RALLY_BOUNDARY_PAD_SEC: float = 0.25


def align_match(
    yolo_frames: list[dict],
    tracknet_frames: list[dict],
    rallies: list[dict],
    court_adapter=None,
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

        events = _build_events(rally_yolo, rally_tracknet, court_adapter=court_adapter)
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
    court_adapter=None,
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
        hitter_label_geometry: Optional[str] = None
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
                    # C-8 / D-5: 同じ側・未校正・4人検出等では推測ラベルを
                    # review_required 上限へ。2人だけが foot_point でネットを挟む
                    # 場合だけ suggested 上限まで許す。D-3 の距離問題が残るため
                    # net-separated でも auto_filled にはしない。
                    hitter_confidence, hitter_label_geometry = cap_guessed_hitter_confidence(
                        hitter_confidence, nearest, players, court_adapter
                    )
                    hitter_confidence = round(hitter_confidence, 3)

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
            "hitter_label_geometry": hitter_label_geometry,
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
