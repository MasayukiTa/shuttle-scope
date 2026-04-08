"""ラリー管理API（/api/rallies）"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Rally, GameSet, Match, Stroke
from backend.utils.sync_meta import touch

router = APIRouter()


class RallyCreate(BaseModel):
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


class RallyUpdate(BaseModel):
    winner: Optional[str] = None
    end_type: Optional[str] = None
    rally_length: Optional[int] = None
    duration_sec: Optional[float] = None
    score_a_after: Optional[int] = None
    score_b_after: Optional[int] = None
    is_deuce: Optional[bool] = None
    video_timestamp_start: Optional[float] = None
    video_timestamp_end: Optional[float] = None


def rally_to_dict(r: Rally) -> dict:
    return {
        "id": r.id,
        "set_id": r.set_id,
        "rally_num": r.rally_num,
        "server": r.server,
        "winner": r.winner,
        "end_type": r.end_type,
        "rally_length": r.rally_length,
        "duration_sec": r.duration_sec,
        "score_a_after": r.score_a_after,
        "score_b_after": r.score_b_after,
        "is_deuce": r.is_deuce,
        "video_timestamp_start": r.video_timestamp_start,
        "video_timestamp_end": r.video_timestamp_end,
    }


@router.post("/rallies", status_code=201)
def create_rally(body: RallyCreate, db: Session = Depends(get_db)):
    """ラリー作成"""
    game_set = db.get(GameSet, body.set_id)
    if not game_set:
        raise HTTPException(status_code=404, detail="セットが見つかりません")
    rally = Rally(**body.model_dump())
    touch(rally)
    db.add(rally)
    db.commit()
    db.refresh(rally)
    return {"success": True, "data": rally_to_dict(rally)}


@router.put("/rallies/{rally_id}")
def update_rally(rally_id: int, body: RallyUpdate, db: Session = Depends(get_db)):
    """ラリー更新"""
    rally = db.get(Rally, rally_id)
    if not rally:
        raise HTTPException(status_code=404, detail="ラリーが見つかりません")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(rally, key, value)
    touch(rally)
    db.commit()
    db.refresh(rally)
    return {"success": True, "data": rally_to_dict(rally)}


@router.delete("/rallies/{rally_id}")
def delete_rally(rally_id: int, db: Session = Depends(get_db)):
    """ラリー削除（アンドゥ用）"""
    rally = db.get(Rally, rally_id)
    if not rally:
        raise HTTPException(status_code=404, detail="ラリーが見つかりません")
    db.delete(rally)
    db.commit()
    return {"success": True, "data": {"id": rally_id}}


@router.get("/annotation/{match_id}/state")
def get_annotation_state(match_id: int, db: Session = Depends(get_db)):
    """アノテーション現在状態（再開用）"""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    # 最後のセットと最後のラリーを取得
    last_set = db.query(GameSet).filter(
        GameSet.match_id == match_id
    ).order_by(GameSet.set_num.desc()).first()

    if not last_set:
        return {
            "success": True,
            "data": {
                "match_id": match_id,
                "current_set_num": 1,
                "current_rally_num": 1,
                "score_a": 0,
                "score_b": 0,
            }
        }

    last_rally = db.query(Rally).filter(
        Rally.set_id == last_set.id
    ).order_by(Rally.rally_num.desc()).first()

    if last_rally:
        return {
            "success": True,
            "data": {
                "match_id": match_id,
                "current_set_num": last_set.set_num,
                "current_rally_num": last_rally.rally_num + 1,
                "score_a": last_rally.score_a_after,
                "score_b": last_rally.score_b_after,
            }
        }

    return {
        "success": True,
        "data": {
            "match_id": match_id,
            "current_set_num": last_set.set_num,
            "current_rally_num": 1,
            "score_a": 0,
            "score_b": 0,
        }
    }


@router.post("/annotation/{match_id}/undo")
def undo_last_stroke(match_id: int, db: Session = Depends(get_db)):
    """最後のストロークを取り消し"""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    last_set = db.query(GameSet).filter(
        GameSet.match_id == match_id
    ).order_by(GameSet.set_num.desc()).first()

    if not last_set:
        raise HTTPException(status_code=400, detail="アンドゥするデータがありません")

    last_rally = db.query(Rally).filter(
        Rally.set_id == last_set.id
    ).order_by(Rally.rally_num.desc()).first()

    if not last_rally:
        raise HTTPException(status_code=400, detail="アンドゥするラリーがありません")

    last_stroke = db.query(Stroke).filter(
        Stroke.rally_id == last_rally.id
    ).order_by(Stroke.stroke_num.desc()).first()

    if last_stroke:
        db.delete(last_stroke)
        db.commit()
        return {"success": True, "data": {"deleted_stroke_id": last_stroke.id}}

    raise HTTPException(status_code=400, detail="アンドゥするストロークがありません")
