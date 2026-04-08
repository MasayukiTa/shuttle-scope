"""ストローク管理API（/api/strokes）"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Stroke, Rally, GameSet, Match
from backend.utils.validators import validate_stroke, validate_rally
from backend.utils.sync_meta import touch
from backend.analysis.shot_taxonomy import canonicalize as canonicalize_shot

router = APIRouter()


class StrokeData(BaseModel):
    stroke_num: int
    player: str
    shot_type: str
    shot_quality: Optional[str] = None
    hit_x: Optional[float] = None
    hit_y: Optional[float] = None
    land_x: Optional[float] = None
    land_y: Optional[float] = None
    hit_zone: Optional[str] = None
    land_zone: Optional[str] = None
    is_backhand: bool = False
    is_around_head: bool = False
    above_net: Optional[bool] = None
    is_cross: bool = False
    timestamp_sec: Optional[float] = None
    # N-002: 空間座標拡張
    opponent_contact_x: Optional[float] = None
    opponent_contact_y: Optional[float] = None
    player_contact_x:   Optional[float] = None
    player_contact_y:   Optional[float] = None
    return_target_x:    Optional[float] = None
    return_target_y:    Optional[float] = None
    # G2: 返球品質・打点高さ（ストローク確定後オプション）
    return_quality: Optional[str] = None   # attack/neutral/defensive/emergency
    contact_height: Optional[str] = None   # overhead/side/underhand/scoop
    # 移動系コンテキスト（4.1 Movement Features）
    contact_zone: Optional[str] = None     # front/mid/rear
    movement_burden: Optional[str] = None  # low/medium/high
    movement_direction: Optional[str] = None  # forward/backward/lateral


class RallyData(BaseModel):
    set_id: int
    rally_num: int
    server: str
    winner: str
    end_type: str
    rally_length: int
    duration_sec: Optional[float] = None
    score_a_after: int
    score_b_after: int
    is_deuce: bool = False
    video_timestamp_start: Optional[float] = None
    video_timestamp_end: Optional[float] = None
    is_skipped: bool = False


class BatchSaveRequest(BaseModel):
    """ラリー確定時の一括保存リクエスト"""
    rally: RallyData
    strokes: list[StrokeData]


def stroke_to_dict(s: Stroke) -> dict:
    return {
        "id": s.id,
        "rally_id": s.rally_id,
        "stroke_num": s.stroke_num,
        "player": s.player,
        "shot_type": s.shot_type,
        "shot_quality": s.shot_quality,
        "hit_x": s.hit_x,
        "hit_y": s.hit_y,
        "land_x": s.land_x,
        "land_y": s.land_y,
        "hit_zone": s.hit_zone,
        "land_zone": s.land_zone,
        "is_backhand": s.is_backhand,
        "is_around_head": s.is_around_head,
        "above_net": s.above_net,
        "is_cross": s.is_cross,
        "timestamp_sec": s.timestamp_sec,
        "epv": s.epv,
        "shot_influence": s.shot_influence,
        "opponent_contact_x": s.opponent_contact_x,
        "opponent_contact_y": s.opponent_contact_y,
        "player_contact_x":   s.player_contact_x,
        "player_contact_y":   s.player_contact_y,
        "return_target_x":    s.return_target_x,
        "return_target_y":    s.return_target_y,
        "return_quality":     s.return_quality,
        "contact_height":     s.contact_height,
        "contact_zone":       s.contact_zone,
        "movement_burden":    s.movement_burden,
        "movement_direction": s.movement_direction,
    }


@router.post("/strokes/batch", status_code=201)
def batch_save_rally(body: BatchSaveRequest, db: Session = Depends(get_db)):
    """ラリー確定時の一括保存（個別保存より効率的）"""
    # セット存在確認
    game_set = db.get(GameSet, body.rally.set_id)
    if not game_set:
        raise HTTPException(status_code=404, detail="セットが見つかりません")

    # ラリー整合性チェック
    stroke_dicts = [s.model_dump() for s in body.strokes]
    rally_dict = body.rally.model_dump()
    valid, error = validate_rally(rally_dict, stroke_dicts)
    if not valid:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": error}
        )

    # 各ストロークの整合性チェック
    for stroke_data in stroke_dicts:
        valid, error = validate_stroke(stroke_data)
        if not valid:
            raise HTTPException(
                status_code=422,
                detail={"code": "VALIDATION_ERROR", "message": error}
            )

    # score_before を前のラリーから自動計算
    prev_rally = (
        db.query(Rally)
        .filter(
            Rally.set_id == body.rally.set_id,
            Rally.rally_num == body.rally.rally_num - 1,
        )
        .first()
    )
    score_a_before = prev_rally.score_a_after if prev_rally else 0
    score_b_before = prev_rally.score_b_after if prev_rally else 0

    # ラリー保存（score_before はサーバー側で計算）
    rally = Rally(**body.rally.model_dump())
    rally.score_a_before = score_a_before
    rally.score_b_before = score_b_before
    db.add(rally)
    db.flush()  # IDを取得するため先にflush

    # ストローク一括保存（shot_type を canonical 化）
    saved_strokes = []
    for stroke_data in body.strokes:
        stroke_dict = stroke_data.model_dump()
        stroke_dict["shot_type"] = canonicalize_shot(stroke_dict.get("shot_type", "other"))
        stroke = Stroke(rally_id=rally.id, **stroke_dict)
        db.add(stroke)
        saved_strokes.append(stroke)

    # アノテーション進捗を更新
    _update_annotation_progress(game_set.match_id, db)

    db.commit()
    db.refresh(rally)

    # S-001: アクティブセッションへスコア更新をブロードキャスト（非同期）
    import asyncio
    from backend.ws.live import manager
    from backend.db.models import SharedSession
    sessions = (
        db.query(SharedSession)
        .filter(SharedSession.match_id == game_set.match_id, SharedSession.is_active.is_(True))
        .all()
    )
    if sessions:
        payload = {
            "type": "rally_saved",
            "data": {
                "rally_num": rally.rally_num,
                "winner": rally.winner,
                "end_type": rally.end_type,
                "score_a": rally.score_a_after,
                "score_b": rally.score_b_after,
                "rally_length": rally.rally_length,
                "is_skipped": rally.is_skipped,
            },
        }
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                for s in sessions:
                    asyncio.ensure_future(manager.broadcast(s.session_code, payload))
        except Exception:
            pass

    return {
        "success": True,
        "data": {
            "rally_id": rally.id,
            "stroke_count": len(saved_strokes),
        }
    }


@router.post("/strokes", status_code=201)
def create_stroke(rally_id: int, body: StrokeData, db: Session = Depends(get_db)):
    """ストローク記録（個別）"""
    rally = db.get(Rally, rally_id)
    if not rally:
        raise HTTPException(status_code=404, detail="ラリーが見つかりません")

    valid, error = validate_stroke(body.model_dump())
    if not valid:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": error}
        )

    stroke = Stroke(rally_id=rally_id, **body.model_dump())
    touch(stroke)
    db.add(stroke)
    db.commit()
    db.refresh(stroke)
    return {"success": True, "data": stroke_to_dict(stroke)}


@router.put("/strokes/{stroke_id}")
def update_stroke(stroke_id: int, body: StrokeData, db: Session = Depends(get_db)):
    """ストローク更新"""
    stroke = db.get(Stroke, stroke_id)
    if not stroke:
        raise HTTPException(status_code=404, detail="ストロークが見つかりません")
    for key, value in body.model_dump().items():
        setattr(stroke, key, value)
    touch(stroke)
    db.commit()
    db.refresh(stroke)
    return {"success": True, "data": stroke_to_dict(stroke)}


@router.delete("/strokes/{stroke_id}")
def delete_stroke(stroke_id: int, db: Session = Depends(get_db)):
    """ストローク削除（アンドゥ用）"""
    stroke = db.get(Stroke, stroke_id)
    if not stroke:
        raise HTTPException(status_code=404, detail="ストロークが見つかりません")
    db.delete(stroke)
    db.commit()
    return {"success": True, "data": {"id": stroke_id}}


def _update_annotation_progress(match_id: int, db: Session) -> None:
    """アノテーション進捗を更新（推定総ラリー数ベース）"""
    match = db.get(Match, match_id)
    if not match:
        return

    # 完了ラリー数を取得
    from sqlalchemy import func
    completed = db.query(func.count(Rally.id)).join(
        GameSet, Rally.set_id == GameSet.id
    ).filter(GameSet.match_id == match_id).scalar() or 0

    # 推定総ラリー数（バドミントン1試合の平均: 60ラリー）
    estimated_total = 60
    progress = min(completed / estimated_total, 1.0)
    match.annotation_progress = progress
    if progress >= 1.0:
        match.annotation_status = "complete"
    elif completed > 0:
        match.annotation_status = "in_progress"
