"""ダブルス CV ポジション解析エンジン

YOLO バッチ検出結果（MatchCVArtifact）をもとにダブルス・ポジション解析を行う。

提供する解析:
  - front_back_occupancy:  前衛/後衛占有率
  - formation_tendency:    陣形傾向（前後陣 vs 平行陣）
  - rotation_transitions:  ラリー間での陣形変化カウント
  - pressure_map:          シャトル着地ゾーン × プレイヤー位置の圧力マップ
  - hitter_distribution:   ヒッター候補の分布（アライメントが存在する場合）

注: CV 出力は assisted/research 扱いであり、annotation truth には書き込まない。
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import Match, GameSet, Rally, Stroke, MatchCVArtifact

logger = logging.getLogger(__name__)


# ─── メインエントリポイント ──────────────────────────────────────────────────

def compute_doubles_cv_analytics(match_id: int, db: Session) -> dict:
    """試合の CV 解析サマリーを返す。

    Returns:
        {
          "available": bool,
          "yolo_frame_count": int,
          "position_summary": {...},
          "formation_tendency": {...},
          "rotation_transitions": int,
          "pressure_map": {...},
          "hitter_distribution": {...} | None,
          "notes": [...],
        }
    """
    notes: list[str] = []

    # YOLO artifact を取得
    yolo_artifact = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "yolo_player_detections",
        )
        .order_by(MatchCVArtifact.created_at.desc())
        .first()
    )
    if not yolo_artifact or not yolo_artifact.data:
        return {
            "available": False,
            "notes": ["YOLO 検出データがありません。プレイヤー位置解析ボタンを押してバッチ処理を実行してください。"],
        }

    frames: list[dict] = json.loads(yolo_artifact.data)
    summary_json = json.loads(yolo_artifact.summary) if yolo_artifact.summary else {}

    # アライメント artifact（あれば）
    alignment_artifact = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "cv_alignment",
        )
        .order_by(MatchCVArtifact.created_at.desc())
        .first()
    )
    alignment: list[dict] = (
        json.loads(alignment_artifact.data)
        if alignment_artifact and alignment_artifact.data
        else []
    )

    # ラリーデータ
    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    set_ids = [s.id for s in sets]
    rallies = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids))
        .order_by(Rally.set_id, Rally.rally_num)
        .all()
    ) if set_ids else []

    # ストロークデータ（着地ゾーン）
    rally_ids = [r.id for r in rallies]
    strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .all()
    ) if rally_ids else []

    # 解析実行
    formation_tendency = _compute_formation_tendency(summary_json)
    rotation_transitions = _compute_rotation_transitions(frames, rallies)
    pressure_map = _compute_pressure_map(frames, strokes)
    hitter_dist = _compute_hitter_distribution(alignment) if alignment else None

    if not alignment:
        notes.append("TrackNet アライメントがありません。'位置統合' ボタンを押すとヒッター候補解析が追加されます。")

    match = db.get(Match, match_id)
    is_doubles = match and match.format in (
        "womens_doubles", "mens_doubles", "mixed_doubles"
    ) if match else False
    if not is_doubles:
        notes.append("シングルス試合です。ダブルス専用指標（陣形・ローテーション）は参考値です。")

    return {
        "available": True,
        "yolo_frame_count": yolo_artifact.frame_count or len(frames),
        "backend_used": yolo_artifact.backend_used,
        "position_summary": summary_json,
        "formation_tendency": formation_tendency,
        "rotation_transitions": rotation_transitions,
        "pressure_map": pressure_map,
        "hitter_distribution": hitter_dist,
        "notes": notes,
    }


# ─── 陣形傾向 ────────────────────────────────────────────────────────────────

def _compute_formation_tendency(summary: dict) -> dict:
    """コート位置サマリーから陣形傾向を計算する。"""
    formations = summary.get("formations", {})
    total = max(sum(formations.values()), 1)

    tendency = {
        k: {"count": v, "ratio": round(v / total, 3)}
        for k, v in formations.items()
    }

    # 優位陣形
    dominant = max(formations, key=formations.get) if formations else "unknown"
    fb_ratio = summary.get("front_back_ratio", 0)
    pa_ratio = summary.get("parallel_ratio", 0)

    style = "不明"
    if fb_ratio > 0.5:
        style = "前後陣傾向"
    elif pa_ratio > 0.5:
        style = "平行陣傾向"
    elif fb_ratio > 0.3 or pa_ratio > 0.3:
        style = "混合陣形"

    return {
        "dominant": dominant,
        "style_label": style,
        "front_back_ratio": fb_ratio,
        "parallel_ratio": pa_ratio,
        "breakdown": tendency,
    }


# ─── ローテーション遷移カウント ───────────────────────────────────────────────

def _compute_rotation_transitions(frames: list[dict], rallies: list[Rally]) -> int:
    """ラリー間で前後陣 ↔ 平行陣が切り替わった回数を返す。"""
    from backend.yolo.court_mapper import classify_formation, summarize_rally_positions

    if not rallies or not frames:
        return 0

    prev_dominant: Optional[str] = None
    transitions = 0

    for r in rallies:
        if r.video_timestamp_start is None:
            continue
        end = r.video_timestamp_end or (r.video_timestamp_start + 10.0)
        rally_summary = summarize_rally_positions(frames, r.video_timestamp_start, end)
        fm = rally_summary.get("formations", {})
        if not fm:
            continue
        current = max(fm, key=fm.get)
        if prev_dominant and prev_dominant != current and current != "unknown":
            transitions += 1
        prev_dominant = current

    return transitions


# ─── 圧力マップ ──────────────────────────────────────────────────────────────

def _compute_pressure_map(frames: list[dict], strokes: list[Stroke]) -> dict:
    """ストローク着地ゾーン × プレイヤー位置の圧力マップを生成する。

    ゾーン別に「そのゾーンへの着地時に player_b（受け手）が前衛にいた割合」を計算。
    front_pressure_by_zone: ゾーン → 受け手が前衛にいた割合
    """
    # タイムスタンプ → フレームの逆引き
    ts_to_frame: dict[float, dict] = {
        round(f["timestamp_sec"], 1): f for f in frames
    }

    zone_pressure: dict[str, list[float]] = defaultdict(list)

    for stroke in strokes:
        if not stroke.land_zone or not stroke.timestamp_sec:
            continue
        ts_key = round(float(stroke.timestamp_sec), 1)
        # 最近傍フレームを探す（±0.5s 以内）
        nearest_frame = None
        best_gap = float("inf")
        for fts, frame in ts_to_frame.items():
            gap = abs(fts - ts_key)
            if gap < best_gap and gap <= 0.5:
                best_gap = gap
                nearest_frame = frame

        if not nearest_frame:
            continue

        players = nearest_frame.get("players", [])
        # player_b（受け手仮定）の depth_band
        p_b = next((p for p in players if p.get("label") == "player_b"), None)
        if p_b:
            is_front = p_b.get("depth_band") == "front"
            zone_pressure[stroke.land_zone].append(1.0 if is_front else 0.0)

    # ゾーン別集計
    zone_summary = {}
    for zone, vals in zone_pressure.items():
        if vals:
            zone_summary[zone] = {
                "sample_count": len(vals),
                "receiver_front_ratio": round(sum(vals) / len(vals), 3),
            }

    return zone_summary


# ─── ヒッター候補分布 ────────────────────────────────────────────────────────

def _compute_hitter_distribution(alignment: list[dict]) -> dict:
    """アライメント結果からヒッター候補の分布を集計する。"""
    total_a = 0
    total_b = 0
    rally_dominant: dict[str, int] = {"player_a": 0, "player_b": 0, "balanced": 0}

    for rally in alignment:
        summary = rally.get("summary", {})
        a = summary.get("hitter_a_count", 0)
        b = summary.get("hitter_b_count", 0)
        total_a += a
        total_b += b
        if a > b * 1.5:
            rally_dominant["player_a"] += 1
        elif b > a * 1.5:
            rally_dominant["player_b"] += 1
        else:
            rally_dominant["balanced"] += 1

    total = max(total_a + total_b, 1)
    return {
        "hitter_a_count": total_a,
        "hitter_b_count": total_b,
        "hitter_a_ratio": round(total_a / total, 3),
        "hitter_b_ratio": round(total_b / total, 3),
        "rally_dominant": rally_dominant,
        "note": "assisted — CV 推定値。精度は動画品質に依存します。",
    }
