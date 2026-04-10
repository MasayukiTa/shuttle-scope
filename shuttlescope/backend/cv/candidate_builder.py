"""CV補助アノテーション候補生成エンジン

TrackNet + YOLO + アライメント出力を統合し、
ストロークごとの落点・打者・ロール候補を生成する。

出力形式（cv_candidates アーティファクトの data フィールドに保存）:
{
  "match_id": int,
  "built_at": str (ISO),
  "rallies": {
    "<rally_id>": RallyCVCandidate,
    ...
  }
}

RallyCVCandidate:
{
  "rally_id": int,
  "cv_assist_available": bool,
  "cv_confidence_summary": {
    "land_zone_fill_rate": float,     # 高確信度着地ゾーン率
    "hitter_fill_rate": float,        # 高確信度打者率
    "avg_confidence": float
  },
  "front_back_role_signal": {         # ダブルス前後ポジション
    "player_a_dominant": "front"|"back"|"mixed",
    "player_b_dominant": "front"|"back"|"mixed",
    "stability": float                # 0=不安定, 1=安定
  } | None,
  "review_reason_codes": [str],
  "strokes": [StrokeCVCandidate]
}

StrokeCVCandidate:
{
  "stroke_id": int | None,
  "stroke_num": int,
  "timestamp_sec": float | None,

  "land_zone": {
    "value": str,
    "confidence_score": float,
    "source": "tracknet",
    "decision_mode": "auto_filled"|"suggested"|"review_required",
    "reason_codes": [str]
  } | None,

  "hitter": {
    "value": "player_a"|"player_b",
    "confidence_score": float,
    "source": "yolo"|"tracknet"|"fusion"|"alignment",
    "decision_mode": "auto_filled"|"suggested"|"review_required",
    "reason_codes": [str]
  } | None,

  "front_back_role": {
    "player_a": "front"|"back"|"unclear",
    "player_b": "front"|"back"|"unclear",
    "confidence": float
  } | None
}
"""
from __future__ import annotations

import bisect
import logging
import math
import statistics
from collections import Counter
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── 信頼度しきい値 ────────────────────────────────────────────────────────────
CONF_HIGH   = 0.72  # auto_filled
CONF_MEDIUM = 0.48  # suggested
# < CONF_MEDIUM → review_required

# TrackNet: 着地候補として有効とする最低信頼度
TRACKNET_MIN_CONF = 0.38

# ヒッター推定: アライメントイベントとストロークタイムスタンプの許容誤差（秒）
HITTER_MATCH_WINDOW_SEC = 0.6

# 着地ゾーン探索: ストロークタイムスタンプから何秒後まで見るか
LAND_SEARCH_WINDOW_SEC = 3.0

# ダブルスロール: Y座標でfront/back判定する境界（正規化0-1）
FRONT_THRESHOLD_Y = 0.42  # y < この値 → front (ネット寄り)
BACK_THRESHOLD_Y  = 0.60  # y > この値 → back (バック側)

# ロール安定性判定: 各フレームでの割合がこれ以上なら "安定"
ROLE_STABILITY_MIN = 0.65


def build_candidates(
    match_id: int,
    rallies_db: list[dict],      # DB から取得したラリー情報（id, video_timestamp_start/end）
    strokes_db: list[dict],      # DB から取得したストローク情報（id, rally_id, stroke_num, timestamp_sec）
    tracknet_frames: list[dict], # TrackNet アーティファクト data（frame list）
    yolo_frames: list[dict],     # YOLO アーティファクト data（frame list）
    alignment_data: list[dict],  # アライメント結果（per-rally list）; 空可
) -> dict:
    """試合全体の CV 候補を生成して返す。

    Returns:
        候補辞書 (cv_candidates アーティファクトの data フィールドに保存する内容)
    """
    # タイムスタンプ索引を事前構築
    tracknet_ts = [f.get("timestamp_sec", 0.0) for f in tracknet_frames]
    yolo_ts     = [f.get("timestamp_sec", 0.0) for f in yolo_frames]

    # アライメント: rally_id → alignment dict
    alignment_by_rally: dict[int, dict] = {
        a["rally_id"]: a for a in alignment_data if "rally_id" in a
    }

    # ストローク: rally_id → [stroke_dict]
    strokes_by_rally: dict[int, list[dict]] = {}
    for s in strokes_db:
        strokes_by_rally.setdefault(s["rally_id"], []).append(s)

    result_rallies: dict[str, dict] = {}

    for rally in rallies_db:
        rally_id = rally["id"]
        start_sec = rally.get("video_timestamp_start") or 0.0
        end_sec   = rally.get("video_timestamp_end") or (start_sec + 60.0)

        rally_strokes = sorted(
            strokes_by_rally.get(rally_id, []),
            key=lambda s: s.get("stroke_num", 0),
        )

        # ラリー内の TrackNet / YOLO フレームを取得
        rally_tracknet = _frames_in_range(tracknet_frames, tracknet_ts,
                                          start_sec - 0.25, end_sec + 0.25)
        rally_yolo     = _frames_in_range(yolo_frames, yolo_ts,
                                          start_sec - 0.25, end_sec + 0.25)

        aln = alignment_by_rally.get(rally_id)

        # ストロークごとの候補生成
        stroke_candidates: list[dict] = []
        land_confs: list[float] = []
        hitter_confs: list[float] = []

        for idx, stroke in enumerate(rally_strokes):
            ts = stroke.get("timestamp_sec")

            # 次のストロークのタイムスタンプ（着地探索上限に使う）
            next_ts: Optional[float] = None
            if idx + 1 < len(rally_strokes):
                next_ts = rally_strokes[idx + 1].get("timestamp_sec")

            land = _infer_land_zone(rally_tracknet, tracknet_ts_local=None, stroke_ts=ts,
                                    next_stroke_ts=next_ts)
            hitter = _infer_hitter(aln, rally_yolo, rally_tracknet, stroke_ts=ts,
                                   stroke_num=stroke.get("stroke_num", 1))
            role = _infer_front_back_role(rally_yolo, stroke_ts=ts) if rally_yolo else None

            if land and land["confidence_score"] is not None:
                land_confs.append(land["confidence_score"])
            if hitter and hitter["confidence_score"] is not None:
                hitter_confs.append(hitter["confidence_score"])

            stroke_candidates.append({
                "stroke_id":    stroke.get("id"),
                "stroke_num":   stroke.get("stroke_num"),
                "timestamp_sec": ts,
                "land_zone":    land,
                "hitter":       hitter,
                "front_back_role": role,
            })

        # ラリー全体のサマリーと要確認コード
        reason_codes = _compute_review_reasons(
            rally_tracknet, aln, stroke_candidates
        )
        lz_fill = sum(
            1 for s in stroke_candidates
            if s["land_zone"] and s["land_zone"]["decision_mode"] != "review_required"
        ) / max(len(stroke_candidates), 1)
        h_fill = sum(
            1 for s in stroke_candidates
            if s["hitter"] and s["hitter"]["decision_mode"] != "review_required"
        ) / max(len(stroke_candidates), 1)
        avg_conf = (
            statistics.mean(land_confs + hitter_confs)
            if (land_confs or hitter_confs) else 0.0
        )

        fb_role = _infer_rally_front_back_role(rally_yolo) if rally_yolo else None

        # ダブルスロール不安定 → 要確認コード追加
        if fb_role and fb_role.get("stability", 1.0) < 0.5:
            if "role_state_unstable" not in reason_codes:
                reason_codes.append("role_state_unstable")

        result_rallies[str(rally_id)] = {
            "rally_id": rally_id,
            "cv_assist_available": len(rally_tracknet) > 0 or len(rally_yolo) > 0,
            "cv_confidence_summary": {
                "land_zone_fill_rate": round(lz_fill, 3),
                "hitter_fill_rate":    round(h_fill, 3),
                "avg_confidence":      round(avg_conf, 3),
            },
            "front_back_role_signal": fb_role,
            "review_reason_codes":    reason_codes,
            "strokes": stroke_candidates,
        }

    return {
        "match_id":  match_id,
        "built_at":  datetime.utcnow().isoformat(),
        "rallies":   result_rallies,
    }


# ── 着地ゾーン推定 ────────────────────────────────────────────────────────────

def _infer_land_zone(
    tracknet_frames: list[dict],
    tracknet_ts_local,  # unused (kept for signature symmetry)
    stroke_ts: Optional[float],
    next_stroke_ts: Optional[float],
) -> Optional[dict]:
    """ストロークタイムスタンプ以降の TrackNet フレームから着地ゾーンを推定する。"""
    if stroke_ts is None:
        return None
    if not tracknet_frames:
        return None

    # ストロークから next_ts or +LAND_SEARCH_WINDOW_SEC の範囲
    search_end = min(
        stroke_ts + LAND_SEARCH_WINDOW_SEC,
        (next_stroke_ts - 0.05) if next_stroke_ts else (stroke_ts + LAND_SEARCH_WINDOW_SEC),
    )

    # 範囲内フレームを抽出（信頼度フィルタ）
    window = [
        f for f in tracknet_frames
        if f.get("timestamp_sec", 0) >= stroke_ts + 0.05
           and f.get("timestamp_sec", 0) <= search_end
           and f.get("confidence", 0) >= TRACKNET_MIN_CONF
           and f.get("zone") is not None
    ]
    if not window:
        return None

    # 着地はウィンドウの後半部分でゾーンが安定するところ
    # 後半 40% のフレームを優先（シャトルが落下しきる直前）
    split = max(1, int(len(window) * 0.6))
    landing_window = window[split:]
    if not landing_window:
        landing_window = window

    zone_counter: Counter = Counter(f["zone"] for f in landing_window if f.get("zone"))
    if not zone_counter:
        return None

    best_zone, count = zone_counter.most_common(1)[0]
    total = len(landing_window)
    zone_consistency = count / total  # 同じゾーンが続く割合

    # 信頼度 = TrackNet の平均 confidence × ゾーン一貫性
    avg_conf = statistics.mean(f["confidence"] for f in landing_window)
    composite_conf = round(avg_conf * zone_consistency, 3)

    decision_mode, reason_codes = _conf_to_decision(composite_conf)

    if zone_consistency < 0.4:
        reason_codes.append("landing_zone_ambiguous")
        # 一貫性が低すぎる場合は強制的に review
        decision_mode = "review_required"

    return {
        "value":            best_zone,
        "confidence_score": composite_conf,
        "source":           "tracknet",
        "decision_mode":    decision_mode,
        "reason_codes":     reason_codes,
    }


# ── 打者推定 ──────────────────────────────────────────────────────────────────

def _infer_hitter(
    alignment: Optional[dict],
    yolo_frames: list[dict],
    tracknet_frames: list[dict],
    stroke_ts: Optional[float],
    stroke_num: int,
) -> Optional[dict]:
    """アライメントデータ優先でヒッターを推定。なければ YOLO 近傍で推定。"""
    if stroke_ts is None:
        return None

    # ── 1. アライメントデータから推定 ─────────────────────────────────────────
    if alignment and alignment.get("events"):
        events = alignment["events"]
        event_ts = [e.get("timestamp_sec", 0.0) for e in events]

        # ストロークタイムスタンプに最近傍のイベントを探す
        idx = bisect.bisect_left(event_ts, stroke_ts)
        best_event = None
        best_gap = float("inf")
        for i in [idx - 1, idx]:
            if 0 <= i < len(events):
                gap = abs(event_ts[i] - stroke_ts)
                if gap < best_gap and gap <= HITTER_MATCH_WINDOW_SEC:
                    best_gap = gap
                    best_event = events[i]

        if best_event and best_event.get("hitter_candidate"):
            hitter_val  = best_event["hitter_candidate"]
            hitter_conf = best_event.get("hitter_confidence", 0.0)
            decision_mode, reason_codes = _conf_to_decision(hitter_conf)
            return {
                "value":            hitter_val,
                "confidence_score": round(hitter_conf, 3),
                "source":           "alignment",
                "decision_mode":    decision_mode,
                "reason_codes":     reason_codes,
            }

    # ── 2. YOLO + TrackNet 直接推定（フォールバック） ────────────────────────
    if not yolo_frames:
        return None

    # ストロークタイムスタンプに最近傍の YOLO フレームを探す
    yolo_ts_list = [f.get("timestamp_sec", 0.0) for f in yolo_frames]
    idx = bisect.bisect_left(yolo_ts_list, stroke_ts)
    best_yolo = None
    best_gap = float("inf")
    for i in [idx - 1, idx]:
        if 0 <= i < len(yolo_ts_list):
            gap = abs(yolo_ts_list[i] - stroke_ts)
            if gap < best_gap and gap <= HITTER_MATCH_WINDOW_SEC:
                best_gap = gap
                best_yolo = yolo_frames[i]

    if best_yolo is None:
        return None

    # TrackNet でシャトル位置を取得
    tracknet_ts_list = [f.get("timestamp_sec", 0.0) for f in tracknet_frames]
    shuttle_x: Optional[float] = None
    shuttle_y: Optional[float] = None
    shuttle_conf: float = 0.0

    idx2 = bisect.bisect_left(tracknet_ts_list, stroke_ts)
    best_tf = None
    best_gap2 = float("inf")
    for i in [idx2 - 1, idx2]:
        if 0 <= i < len(tracknet_ts_list):
            gap = abs(tracknet_ts_list[i] - stroke_ts)
            if gap < best_gap2 and gap <= HITTER_MATCH_WINDOW_SEC:
                best_gap2 = gap
                best_tf = tracknet_frames[i]

    if best_tf and best_tf.get("confidence", 0) >= 0.4:
        shuttle_x = best_tf.get("x_norm")
        shuttle_y = best_tf.get("y_norm")
        shuttle_conf = best_tf.get("confidence", 0.0)

    if shuttle_x is None or shuttle_y is None:
        return None

    # 最近傍プレイヤー候補
    players = best_yolo.get("players", [])
    nearest_label: Optional[str] = None
    nearest_dist: float = float("inf")

    for p in players:
        cx, cy = p.get("centroid", [None, None])
        if cx is None or cy is None:
            continue
        label = p.get("label")
        if label not in ("player_a", "player_b"):
            continue
        dist = math.sqrt((cx - shuttle_x) ** 2 + (cy - shuttle_y) ** 2)
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_label = label

    if nearest_label is None or nearest_dist > 0.35:
        return None

    # 距離から信頼度算出（線形減衰）
    hitter_conf = round((1.0 - nearest_dist / 0.35) * shuttle_conf, 3)
    decision_mode, reason_codes = _conf_to_decision(hitter_conf)

    # プレイヤーが複数いて近い場合は ambiguous
    near_players = [
        p for p in players
        if p.get("label") in ("player_a", "player_b")
        and _player_dist(p, shuttle_x, shuttle_y) <= 0.35
    ]
    if len(near_players) >= 2:
        reason_codes.append("multiple_near_players")

    return {
        "value":            nearest_label,
        "confidence_score": hitter_conf,
        "source":           "fusion",
        "decision_mode":    decision_mode,
        "reason_codes":     reason_codes,
    }


# ── ダブルスロール推定（ストロークレベル） ────────────────────────────────────

def _infer_front_back_role(
    yolo_frames: list[dict],
    stroke_ts: Optional[float] = None,
) -> Optional[dict]:
    """指定タイムスタンプ付近のフレームからダブルスの前後ポジションを推定する。"""
    if not yolo_frames:
        return None

    if stroke_ts is not None:
        yolo_ts_list = [f.get("timestamp_sec", 0.0) for f in yolo_frames]
        idx = bisect.bisect_left(yolo_ts_list, stroke_ts)
        nearby = []
        for i in range(max(0, idx - 2), min(len(yolo_frames), idx + 3)):
            nearby.append(yolo_frames[i])
    else:
        nearby = yolo_frames

    if not nearby:
        return None

    # 各プレイヤーの平均 Y 位置を計算
    y_values: dict[str, list[float]] = {"player_a": [], "player_b": []}
    for frame in nearby:
        for p in frame.get("players", []):
            label = p.get("label")
            if label in y_values:
                cy = p.get("centroid", [None, None])[1]
                if cy is not None:
                    y_values[label].append(cy)

    if not y_values["player_a"] and not y_values["player_b"]:
        return None

    def classify_y(ys: list[float]) -> tuple[str, float]:
        if not ys:
            return "unclear", 0.0
        avg_y = statistics.mean(ys)
        if avg_y < FRONT_THRESHOLD_Y:
            conf = min(1.0, (FRONT_THRESHOLD_Y - avg_y) / FRONT_THRESHOLD_Y)
            return "front", round(conf, 3)
        elif avg_y > BACK_THRESHOLD_Y:
            conf = min(1.0, (avg_y - BACK_THRESHOLD_Y) / (1.0 - BACK_THRESHOLD_Y))
            return "back", round(conf, 3)
        else:
            return "unclear", 0.3

    role_a, conf_a = classify_y(y_values["player_a"])
    role_b, conf_b = classify_y(y_values["player_b"])
    avg_role_conf = round((conf_a + conf_b) / 2, 3)

    return {
        "player_a":  role_a,
        "player_b":  role_b,
        "confidence": avg_role_conf,
    }


# ── ラリーレベルのダブルスロール推定 ─────────────────────────────────────────

def _infer_rally_front_back_role(yolo_frames: list[dict]) -> Optional[dict]:
    """ラリー全体の YOLO フレームからダブルス役割安定性を推定する。"""
    if not yolo_frames:
        return None

    frame_roles_a: list[str] = []
    frame_roles_b: list[str] = []

    for frame in yolo_frames:
        for p in frame.get("players", []):
            label = p.get("label")
            cy = p.get("centroid", [None, None])[1]
            if cy is None:
                continue
            if label == "player_a":
                frame_roles_a.append("front" if cy < FRONT_THRESHOLD_Y else
                                     "back" if cy > BACK_THRESHOLD_Y else "unclear")
            elif label == "player_b":
                frame_roles_b.append("front" if cy < FRONT_THRESHOLD_Y else
                                     "back" if cy > BACK_THRESHOLD_Y else "unclear")

    def dominant(roles: list[str]) -> str:
        if not roles:
            return "mixed"
        c = Counter(roles)
        top, cnt = c.most_common(1)[0]
        if cnt / len(roles) >= ROLE_STABILITY_MIN:
            return top if top != "unclear" else "mixed"
        return "mixed"

    def stability(roles: list[str]) -> float:
        if not roles:
            return 0.0
        c = Counter(roles)
        _, cnt = c.most_common(1)[0]
        return round(cnt / len(roles), 3)

    dom_a = dominant(frame_roles_a)
    dom_b = dominant(frame_roles_b)
    stab = round(
        (stability(frame_roles_a) + stability(frame_roles_b)) / 2, 3
    ) if (frame_roles_a or frame_roles_b) else 0.0

    return {
        "player_a_dominant": dom_a,
        "player_b_dominant": dom_b,
        "stability":         stab,
    }


# ── レビュー理由コード計算 ────────────────────────────────────────────────────

def _compute_review_reasons(
    tracknet_frames: list[dict],
    alignment: Optional[dict],
    stroke_candidates: list[dict],
) -> list[str]:
    codes: list[str] = []

    if not tracknet_frames:
        codes.append("low_frame_coverage")
    elif len(tracknet_frames) < 5:
        codes.append("low_frame_coverage")

    if alignment is None:
        codes.append("alignment_missing")

    # 過半数のストロークで landing zone が review_required なら全体も
    n_review = sum(
        1 for s in stroke_candidates
        if s.get("land_zone") and s["land_zone"]["decision_mode"] == "review_required"
    )
    if stroke_candidates and n_review / len(stroke_candidates) >= 0.5:
        codes.append("landing_zone_ambiguous")

    # 打者が特定できなかったストロークが多い
    n_no_hitter = sum(1 for s in stroke_candidates if not s.get("hitter"))
    if stroke_candidates and n_no_hitter / len(stroke_candidates) >= 0.6:
        codes.append("hitter_undetected")

    return codes


# ── ユーティリティ ────────────────────────────────────────────────────────────

def _conf_to_decision(conf: float) -> tuple[str, list[str]]:
    """信頼度スコアから decision_mode と reason_codes を返す。"""
    if conf >= CONF_HIGH:
        return "auto_filled", ["track_present_high_confidence"]
    elif conf >= CONF_MEDIUM:
        return "suggested", []
    else:
        return "review_required", []


def _frames_in_range(frames: list[dict], timestamps: list[float],
                     start: float, end: float) -> list[dict]:
    lo = bisect.bisect_left(timestamps, start)
    hi = bisect.bisect_right(timestamps, end)
    return frames[lo:hi]


def _player_dist(player: dict, sx: float, sy: float) -> float:
    cx, cy = player.get("centroid", [None, None])
    if cx is None or cy is None:
        return float("inf")
    return math.sqrt((cx - sx) ** 2 + (cy - sy) ** 2)
