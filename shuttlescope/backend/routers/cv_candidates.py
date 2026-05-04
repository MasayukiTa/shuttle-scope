"""CV補助アノテーション候補API（/api/cv-candidates）

エンドポイント:
  POST /cv-candidates/build/{match_id}   — 候補を生成してアーティファクトに保存
  GET  /cv-candidates/{match_id}         — 生成済み候補を返す
  POST /cv-candidates/apply/{match_id}   — 高確信度候補をストロークに書き戻す
  PUT  /cv-candidates/review/{rally_id}  — ラリーのレビューステータスを更新
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke, MatchCVArtifact
from backend.cv.candidate_builder import build_candidates
from backend.yolo.cv_aligner import align_match

logger = logging.getLogger(__name__)
router = APIRouter()

ARTIFACT_TYPE_CANDIDATES = "cv_candidates"
ARTIFACT_TYPE_TRACKNET   = "tracknet_shuttle_track"
ARTIFACT_TYPE_YOLO       = "yolo_player_detections"
ARTIFACT_TYPE_ALIGNMENT  = "cv_alignment"


# ────────────────────────────────────────────────────────────────────────────
# POST /cv-candidates/build/{match_id}
# ────────────────────────────────────────────────────────────────────────────

@router.post("/cv-candidates/build/{match_id}")
def build_cv_candidates(match_id: int, db: Session = Depends(get_db)):
    """TrackNet + YOLO アーティファクトから CV 候補を生成して保存する。

    どちらかのアーティファクトが欠けていても部分的な候補を生成する。
    """
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    # ── アーティファクト取得 ──────────────────────────────────────────────────
    tracknet_artifact = _latest_artifact(db, match_id, ARTIFACT_TYPE_TRACKNET)
    yolo_artifact     = _latest_artifact(db, match_id, ARTIFACT_TYPE_YOLO)
    alignment_artifact = _latest_artifact(db, match_id, ARTIFACT_TYPE_ALIGNMENT)

    tracknet_frames: list[dict] = []
    yolo_frames: list[dict]     = []
    alignment_data: list[dict]  = []

    if tracknet_artifact and tracknet_artifact.data:
        try:
            tracknet_frames = json.loads(tracknet_artifact.data)
        except Exception:
            logger.warning("TrackNet artifact JSON 解析失敗 match_id=%d", match_id)

    if yolo_artifact and yolo_artifact.data:
        try:
            yolo_frames = json.loads(yolo_artifact.data)
        except Exception:
            logger.warning("YOLO artifact JSON 解析失敗 match_id=%d", match_id)

    if alignment_artifact and alignment_artifact.data:
        try:
            alignment_data = json.loads(alignment_artifact.data)
        except Exception:
            logger.warning("アライメント artifact JSON 解析失敗 match_id=%d", match_id)

    # アライメントデータがなく両方揃っていれば即時計算
    if not alignment_data and tracknet_frames and yolo_frames:
        rally_boundaries = _get_rally_boundaries(db, match_id)
        try:
            alignment_data = align_match(yolo_frames, tracknet_frames, rally_boundaries)
        except Exception as e:
            logger.warning("アライメント計算失敗: %s", e)

    if not tracknet_frames and not yolo_frames:
        raise HTTPException(
            status_code=400,
            detail="TrackNet または YOLO アーティファクトが必要です。先に CV 解析を実行してください。",
        )

    # ── DB からラリー・ストローク情報を取得 ──────────────────────────────────
    rallies_db = _get_rallies_for_match(db, match_id)
    rally_ids  = [r["id"] for r in rallies_db]
    strokes_db = _get_strokes_for_rallies(db, rally_ids)

    # ── 候補生成 ─────────────────────────────────────────────────────────────
    candidates = build_candidates(
        match_id=match_id,
        rallies_db=rallies_db,
        strokes_db=strokes_db,
        tracknet_frames=tracknet_frames,
        yolo_frames=yolo_frames,
        alignment_data=alignment_data,
    )

    candidates_json = json.dumps(candidates, ensure_ascii=False)

    # ── アーティファクト保存（既存があれば上書き） ────────────────────────────
    existing = _latest_artifact(db, match_id, ARTIFACT_TYPE_CANDIDATES)
    if existing:
        existing.data       = candidates_json
        existing.summary    = json.dumps({
            "rally_count": len(candidates["rallies"]),
            "built_at":    candidates["built_at"],
        }, ensure_ascii=False)
        existing.updated_at = datetime.utcnow()
    else:
        artifact = MatchCVArtifact(
            match_id      = match_id,
            artifact_type = ARTIFACT_TYPE_CANDIDATES,
            summary       = json.dumps({
                "rally_count": len(candidates["rallies"]),
                "built_at":    candidates["built_at"],
            }, ensure_ascii=False),
            data          = candidates_json,
        )
        db.add(artifact)

    db.commit()

    return {
        "success": True,
        "data": {
            "match_id":    match_id,
            "rally_count": len(candidates["rallies"]),
            "built_at":    candidates["built_at"],
        },
    }


# ────────────────────────────────────────────────────────────────────────────
# GET /cv-candidates/{match_id}
# ────────────────────────────────────────────────────────────────────────────

@router.get("/cv-candidates/{match_id}")
def get_cv_candidates(match_id: int, db: Session = Depends(get_db)):
    """生成済み CV 候補を返す。未生成の場合は data: null を返す。"""
    artifact = _latest_artifact(db, match_id, ARTIFACT_TYPE_CANDIDATES)
    if not artifact or not artifact.data:
        return {"success": True, "data": None}

    try:
        data = json.loads(artifact.data)
    except Exception:
        return {"success": True, "data": None}

    return {"success": True, "data": data}


# ────────────────────────────────────────────────────────────────────────────
# POST /cv-candidates/apply/{match_id}
# ────────────────────────────────────────────────────────────────────────────

class ApplyRequest(BaseModel):
    mode: str = "auto_filled"  # "auto_filled" | "suggested" | "all"
    fields: list[str] = ["land_zone", "hitter"]  # 適用するフィールド


@router.post("/cv-candidates/apply/{match_id}")
def apply_cv_candidates(
    match_id: int,
    body: ApplyRequest,
    db: Session = Depends(get_db),
):
    """候補を既存ストロークに書き戻す。

    - mode="auto_filled": decision_mode=="auto_filled" の候補のみ適用
    - mode="suggested": auto_filled + suggested を適用
    - mode="all": 全候補を適用（確認なし）
    """
    artifact = _latest_artifact(db, match_id, ARTIFACT_TYPE_CANDIDATES)
    if not artifact or not artifact.data:
        raise HTTPException(status_code=404, detail="CV 候補がありません。先にビルドを実行してください。")

    try:
        candidates = json.loads(artifact.data)
    except Exception:
        raise HTTPException(status_code=500, detail="候補データの解析に失敗しました")

    # 適用モード
    apply_modes: set[str] = {"auto_filled"}
    if body.mode in ("suggested", "all"):
        apply_modes.add("suggested")
    if body.mode == "all":
        apply_modes.add("review_required")

    updated_count = 0
    land_zone_count = 0
    hitter_count = 0

    for rally_cand in candidates.get("rallies", {}).values():
        for sc in rally_cand.get("strokes", []):
            stroke_id = sc.get("stroke_id")
            if not stroke_id:
                continue

            stroke = db.get(Stroke, stroke_id)
            if not stroke:
                continue

            changed = False

            # 着地ゾーン書き戻し
            if "land_zone" in body.fields:
                lz = sc.get("land_zone")
                if lz and lz.get("decision_mode") in apply_modes:
                    if stroke.land_zone != lz["value"]:
                        stroke.land_zone = lz["value"]
                        land_zone_count += 1
                        changed = True

            # 打者書き戻し
            if "hitter" in body.fields:
                ht = sc.get("hitter")
                if ht and ht.get("decision_mode") in apply_modes:
                    # player フィールドに書き戻す
                    if stroke.player != ht["value"]:
                        stroke.player = ht["value"]
                        hitter_count += 1
                        changed = True

            if changed:
                stroke.source_method = "assisted"
                updated_count += 1

    db.commit()

    return {
        "success": True,
        "data": {
            "updated_strokes": updated_count,
            "land_zone_count": land_zone_count,
            "hitter_count":    hitter_count,
            "applied_by_mode": body.mode,
            "applied_fields":  list(body.fields),
        },
    }


# ────────────────────────────────────────────────────────────────────────────
# PUT /cv-candidates/review/{rally_id}
# ────────────────────────────────────────────────────────────────────────────

class ReviewStatusUpdate(BaseModel):
    review_status: str  # "pending" | "completed"


@router.put("/cv-candidates/review/{rally_id}")
def update_rally_review_status(
    rally_id: int,
    body: ReviewStatusUpdate,
    db: Session = Depends(get_db),
):
    """ラリーのレビューステータスを更新する。"""
    rally = db.get(Rally, rally_id)
    if not rally:
        raise HTTPException(status_code=404, detail="ラリーが見つかりません")

    if body.review_status not in ("pending", "completed"):
        raise HTTPException(status_code=400, detail="review_status は pending / completed のいずれかです")

    rally.review_status = body.review_status
    db.commit()

    return {"success": True, "data": {"rally_id": rally_id, "review_status": body.review_status}}


# ────────────────────────────────────────────────────────────────────────────
# GET /cv-candidates/review-queue/{match_id}
# ────────────────────────────────────────────────────────────────────────────

@router.get("/cv-candidates/review-queue/{match_id}")
def get_review_queue(match_id: int, db: Session = Depends(get_db)):
    """review_status='pending' のラリー一覧を返す（自動フラグ + 手動フラグ両方）。"""
    # 手動フラグされたラリー
    sets = (
        db.query(GameSet)
        .filter(GameSet.match_id == match_id)
        .all()
    )
    set_ids = [s.id for s in sets]
    if not set_ids:
        return {"success": True, "data": []}

    pending_rallies = (
        db.query(Rally)
        .filter(
            Rally.set_id.in_(set_ids),
            Rally.review_status == "pending",
        )
        .order_by(Rally.rally_num)
        .all()
    )

    # CV 候補からも review_required フラグを取得
    artifact = _latest_artifact(db, match_id, ARTIFACT_TYPE_CANDIDATES)
    cv_review_reasons: dict[int, list[str]] = {}
    if artifact and artifact.data:
        try:
            candidates = json.loads(artifact.data)
            for rally_id_str, rc in candidates.get("rallies", {}).items():
                if rc.get("review_reason_codes"):
                    cv_review_reasons[int(rally_id_str)] = rc["review_reason_codes"]
        except Exception:
            pass

    result = []
    for rally in pending_rallies:
        result.append({
            "rally_id":    rally.id,
            "rally_num":   rally.rally_num,
            "set_id":      rally.set_id,
            "review_status": rally.review_status,
            "cv_reason_codes": cv_review_reasons.get(rally.id, []),
        })

    # CV 候補で要確認だが review_status が pending でないものも追加
    for rally_id, codes in cv_review_reasons.items():
        if not any(r["rally_id"] == rally_id for r in result):
            rally = db.get(Rally, rally_id)
            if rally:
                result.append({
                    "rally_id":    rally.id,
                    "rally_num":   rally.rally_num,
                    "set_id":      rally.set_id,
                    "review_status": rally.review_status or "pending",
                    "cv_reason_codes": codes,
                })

    result.sort(key=lambda r: r["rally_num"])
    return {"success": True, "data": result}


# ── ヘルパー ──────────────────────────────────────────────────────────────────

def _latest_artifact(db: Session, match_id: int, artifact_type: str) -> Optional[MatchCVArtifact]:
    return (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == artifact_type,
        )
        .order_by(MatchCVArtifact.created_at.desc())
        .first()
    )


def _get_rally_boundaries(db: Session, match_id: int) -> list[dict]:
    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    set_ids = [s.id for s in sets]
    if not set_ids:
        return []
    rallies = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids))
        .order_by(Rally.id)
        .all()
    )
    return [
        {
            "rally_id": r.id,
            "start_sec": r.video_timestamp_start or 0.0,
            "end_sec":   r.video_timestamp_end or 0.0,
        }
        for r in rallies
    ]


def _get_rallies_for_match(db: Session, match_id: int) -> list[dict]:
    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    set_ids = [s.id for s in sets]
    if not set_ids:
        return []
    rallies = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids))
        .order_by(Rally.id)
        .all()
    )
    return [
        {
            "id":                    r.id,
            "set_id":                r.set_id,
            "rally_num":             r.rally_num,
            "video_timestamp_start": r.video_timestamp_start,
            "video_timestamp_end":   r.video_timestamp_end,
            "review_status":         r.review_status,
            "annotation_mode":       r.annotation_mode,
        }
        for r in rallies
    ]


def _get_strokes_for_rallies(db: Session, rally_ids: list[int]) -> list[dict]:
    if not rally_ids:
        return []
    strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )
    return [
        {
            "id":           s.id,
            "rally_id":     s.rally_id,
            "stroke_num":   s.stroke_num,
            "player":       s.player,
            "shot_type":    s.shot_type,
            "timestamp_sec": s.timestamp_sec,
            "land_zone":    s.land_zone,
            "source_method": s.source_method,
        }
        for s in strokes
    ]
