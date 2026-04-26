"""ラリー管理API（/api/rallies）"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Rally, GameSet, Match, Stroke
from backend.utils.sync_meta import touch
from backend.utils import response_cache
from backend.utils.match_players import players_for_set, players_for_rally

router = APIRouter()


def _rally_require_scope(request: Request, db: Session, set_id: int) -> Match:
    """rally が属する match を取得し、analyst/coach の team scope を検証する。
    admin 無条件許可、player は参加試合のみ。"""
    gs = db.get(GameSet, set_id)
    if not gs:
        raise HTTPException(status_code=404, detail="セットが見つかりません")
    match = db.get(Match, gs.match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    from backend.utils.auth import require_match_scope
    require_match_scope(request, match, db)
    return match


class RallyCreate(BaseModel):
    # 未知フィールド禁止 (mass assignment 防御)
    model_config = {"extra": "forbid"}
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
    model_config = {"extra": "forbid"}
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
def create_rally(body: RallyCreate, request: Request, db: Session = Depends(get_db)):
    """ラリー作成"""
    # player 書込み拒否 + analyst/coach の team scope 検証
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    _rally_require_scope(request, db, body.set_id)
    rally = Rally(**body.model_dump())
    touch(rally)
    db.add(rally)
    db.commit()
    # set_id から辿って試合の関与選手のみ無効化
    response_cache.bump_players(players_for_set(db, body.set_id))
    db.refresh(rally)
    return {"success": True, "data": rally_to_dict(rally)}


@router.put("/rallies/{rally_id}")
def update_rally(rally_id: int, body: RallyUpdate, request: Request, db: Session = Depends(get_db)):
    """ラリー更新"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    rally = db.get(Rally, rally_id)
    if not rally:
        raise HTTPException(status_code=404, detail="ラリーが見つかりません")
    _rally_require_scope(request, db, rally.set_id)
    from backend.utils.db_update import apply_update
    apply_update(rally, body.model_dump(exclude_unset=True))
    touch(rally)
    db.commit()
    # 対象 rally の試合の関与選手のみ無効化
    response_cache.bump_players(players_for_set(db, rally.set_id))
    db.refresh(rally)
    return {"success": True, "data": rally_to_dict(rally)}


@router.delete("/rallies/{rally_id}")
def delete_rally(rally_id: int, request: Request, db: Session = Depends(get_db)):
    """ラリー削除（アンドゥ用）"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    rally = db.get(Rally, rally_id)
    if not rally:
        raise HTTPException(status_code=404, detail="ラリーが見つかりません")
    _rally_require_scope(request, db, rally.set_id)
    # 削除前に関与選手を控える
    affected_players = players_for_set(db, rally.set_id)
    db.delete(rally)
    db.commit()
    response_cache.bump_players(affected_players)
    return {"success": True, "data": {"id": rally_id}}


@router.get("/annotation/{match_id}/state")
def get_annotation_state(match_id: int, request: Request, db: Session = Depends(get_db)):
    """アノテーション現在状態（再開用）"""
    from backend.utils.auth import get_auth as _ga
    from fastapi import HTTPException as _HE
    _ctx = _ga(request)
    if _ctx.role is None:
        from backend.utils.control_plane import allow_legacy_header_auth
        if not allow_legacy_header_auth(request):
            raise _HE(status_code=401, detail="認証が必要です")
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    from backend.utils.auth import user_can_access_match
    if not _ctx.is_admin and not user_can_access_match(_ctx, match):
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
def undo_last_stroke(match_id: int, request: Request, db: Session = Depends(get_db)):
    """最後のストロークを取り消し"""
    from backend.utils.auth import get_auth as _ga, user_can_access_match
    from fastapi import HTTPException as _HE
    _ctx = _ga(request)
    if _ctx.role is None:
        from backend.utils.control_plane import allow_legacy_header_auth
        if not allow_legacy_header_auth(request):
            raise _HE(status_code=401, detail="認証が必要です")
    if _ctx.is_player:
        raise _HE(status_code=403, detail="この操作を行う権限がありません")
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    if not _ctx.is_admin and not user_can_access_match(_ctx, match):
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
        # match_id は既に確定しているので、そこから関与選手のみ無効化
        from backend.utils.match_players import players_for_match
        response_cache.bump_players(players_for_match(db, match_id))
        return {"success": True, "data": {"deleted_stroke_id": last_stroke.id}}

    raise HTTPException(status_code=400, detail="アンドゥするストロークがありません")
