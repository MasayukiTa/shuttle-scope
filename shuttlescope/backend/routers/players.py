"""選手管理API（/api/players）"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Player, Match

router = APIRouter()


class PlayerCreate(BaseModel):
    name: str
    name_en: Optional[str] = None
    team: Optional[str] = None
    nationality: Optional[str] = None
    dominant_hand: str = "R"
    birth_year: Optional[int] = None
    world_ranking: Optional[int] = None
    is_target: bool = False
    notes: Optional[str] = None


class PlayerUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    team: Optional[str] = None
    nationality: Optional[str] = None
    dominant_hand: Optional[str] = None
    birth_year: Optional[int] = None
    world_ranking: Optional[int] = None
    is_target: Optional[bool] = None
    notes: Optional[str] = None


def player_to_dict(p: Player, match_count: int = 0) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "name_en": p.name_en,
        "team": p.team,
        "nationality": p.nationality,
        "dominant_hand": p.dominant_hand,
        "birth_year": p.birth_year,
        "world_ranking": p.world_ranking,
        "is_target": p.is_target,
        "match_count": match_count,
        "notes": p.notes,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("/players")
def list_players(db: Session = Depends(get_db)):
    """選手一覧（試合数付き）"""
    players = db.query(Player).order_by(Player.name).all()
    result = []
    for p in players:
        cnt = db.query(Match).filter(
            (Match.player_a_id == p.id) | (Match.player_b_id == p.id)
        ).count()
        result.append(player_to_dict(p, match_count=cnt))
    return {"success": True, "data": result}


@router.post("/players", status_code=201)
def create_player(body: PlayerCreate, db: Session = Depends(get_db)):
    """選手登録"""
    player = Player(**body.model_dump())
    db.add(player)
    db.commit()
    db.refresh(player)
    return {"success": True, "data": player_to_dict(player)}


@router.get("/players/{player_id}")
def get_player(player_id: int, db: Session = Depends(get_db)):
    """選手詳細"""
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    return {"success": True, "data": player_to_dict(player)}


@router.put("/players/{player_id}")
def update_player(player_id: int, body: PlayerUpdate, db: Session = Depends(get_db)):
    """選手更新"""
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(player, key, value)
    db.commit()
    db.refresh(player)
    return {"success": True, "data": player_to_dict(player)}


@router.delete("/players/{player_id}")
def delete_player(player_id: int, db: Session = Depends(get_db)):
    """選手削除"""
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    db.delete(player)
    db.commit()
    return {"success": True, "data": {"id": player_id}}


@router.get("/players/{player_id}/matches")
def get_player_matches(player_id: int, db: Session = Depends(get_db)):
    """選手の試合一覧"""
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    matches = db.query(Match).filter(
        (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
    ).order_by(Match.date.desc()).all()
    return {"success": True, "data": [
        {
            "id": m.id,
            "tournament": m.tournament,
            "date": m.date.isoformat() if m.date else None,
            "result": m.result,
            "annotation_status": m.annotation_status,
            "annotation_progress": m.annotation_progress,
        }
        for m in matches
    ]}


@router.get("/players/{player_id}/stats")
def get_player_stats(player_id: int, db: Session = Depends(get_db)):
    """選手の基礎スタッツ"""
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    total_matches = db.query(Match).filter(
        (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
    ).count()
    wins = db.query(Match).filter(
        Match.player_a_id == player_id, Match.result == "win"
    ).count()
    return {
        "success": True,
        "data": {
            "total_matches": total_matches,
            "wins": wins,
        }
    }
