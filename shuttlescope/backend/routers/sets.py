"""セット管理API（/api/sets）"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Rally
from backend.utils.sync_meta import touch
from backend.utils import response_cache
from backend.utils.match_players import players_for_match

router = APIRouter()


class SetCreate(BaseModel):
    # extra フィールド禁止 + set_num は 1-5 に制限 (ベスト 3 of 5 相当)
    # これは badminton の公式ルールに従う。99 等の不正値を 422 で弾く
    model_config = {"extra": "forbid"}
    match_id: int
    set_num: int = Field(..., ge=1, le=5)


class SetEnd(BaseModel):
    model_config = {"extra": "forbid"}
    winner: str = Field(..., pattern="^(player_a|player_b)$")
    score_a: int = Field(..., ge=0, le=40)  # デュース含め 30 前後が最大、40 で余裕
    score_b: int = Field(..., ge=0, le=40)


def set_to_dict(s: GameSet) -> dict:
    return {
        "id": s.id,
        "match_id": s.match_id,
        "set_num": s.set_num,
        "winner": s.winner,
        "score_a": s.score_a,
        "score_b": s.score_b,
        "is_deuce": s.is_deuce,
    }


@router.get("/sets/match/{match_id}")
def get_sets(match_id: int, db: Session = Depends(get_db)):
    """試合のセット一覧"""
    sets = db.query(GameSet).filter(
        GameSet.match_id == match_id
    ).order_by(GameSet.set_num).all()
    return {"success": True, "data": [set_to_dict(s) for s in sets]}


@router.post("/sets", status_code=201)
def create_set(body: SetCreate, db: Session = Depends(get_db)):
    """セット作成（重複チェックあり）"""
    match = db.get(Match, body.match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    # 既に同じセット番号が存在する場合はそれを返す
    existing = db.query(GameSet).filter(
        GameSet.match_id == body.match_id,
        GameSet.set_num == body.set_num,
    ).first()
    if existing:
        return {"success": True, "data": set_to_dict(existing)}

    game_set = GameSet(match_id=body.match_id, set_num=body.set_num)
    touch(game_set)
    db.add(game_set)
    db.commit()
    # 試合の関与選手のみキャッシュ無効化
    response_cache.bump_players(players_for_match(db, body.match_id))
    db.refresh(game_set)
    return {"success": True, "data": set_to_dict(game_set)}


@router.put("/sets/{set_id}/end")
def end_set(set_id: int, body: SetEnd, db: Session = Depends(get_db)):
    """セット終了（スコア・勝者確定）"""
    game_set = db.get(GameSet, set_id)
    if not game_set:
        raise HTTPException(status_code=404, detail="セットが見つかりません")

    game_set.winner = body.winner
    game_set.score_a = body.score_a
    game_set.score_b = body.score_b
    game_set.is_deuce = body.score_a >= 20 and body.score_b >= 20
    touch(game_set)
    db.commit()
    # 終了したセットの試合の関与選手のみ無効化
    response_cache.bump_players(players_for_match(db, game_set.match_id))
    db.refresh(game_set)
    return {"success": True, "data": set_to_dict(game_set)}


@router.get("/sets/{set_id}/rally_count")
def get_rally_count(set_id: int, db: Session = Depends(get_db)):
    """セット内のラリー数（次のラリー番号算出用）"""
    count = db.query(func.count(Rally.id)).filter(Rally.set_id == set_id).scalar() or 0
    return {"success": True, "data": {"count": count, "next_rally_num": count + 1}}
