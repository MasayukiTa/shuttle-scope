"""選手管理API（/api/players）"""
import json
import re
import unicodedata
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Player, Match
from backend.utils.auth import get_auth, require_analyst
from backend.utils.sync_meta import touch
from backend.utils import response_cache

router = APIRouter()


class PlayerCreate(BaseModel):
    name: str
    name_en: Optional[str] = None
    team: Optional[str] = None
    nationality: Optional[str] = None
    dominant_hand: Optional[str] = "unknown"    # R / L / unknown（未確認時はunknown）
    birth_year: Optional[int] = None
    world_ranking: Optional[int] = None
    is_target: bool = False
    notes: Optional[str] = None
    # V4: プロフィール確定度・暫定作成管理
    profile_status: Optional[str] = "verified"
    needs_review: bool = False
    created_via_quick_start: bool = False
    organization: Optional[str] = None
    aliases: Optional[list[str]] = None
    scouting_notes: Optional[str] = None


class TeamHistoryEntry(BaseModel):
    team: str
    until: Optional[str] = None   # "2025-03" など任意の文字列
    note: Optional[str] = None


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
    # V4
    profile_status: Optional[str] = None
    needs_review: Optional[bool] = None
    organization: Optional[str] = None
    aliases: Optional[list[str]] = None
    scouting_notes: Optional[str] = None
    # 所属履歴（手動上書き用。通常は team 変更時に自動追記される）
    team_history: Optional[list[TeamHistoryEntry]] = None


def normalize_name(name: str) -> str:
    """検索用の正規化名を生成する（全角→半角、大文字→小文字、スペース・記号除去）"""
    # Unicode正規化（全角→半角）
    normalized = unicodedata.normalize("NFKC", name)
    # 大文字→小文字
    normalized = normalized.lower()
    # スペース・記号除去
    normalized = re.sub(r"[\s\-_.・]", "", normalized)
    return normalized


def _parse_json_list(raw: Optional[str]) -> list:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


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
        # V4
        "profile_status": p.profile_status or "verified",
        "needs_review": bool(p.needs_review),
        "created_via_quick_start": bool(p.created_via_quick_start),
        "organization": p.organization,
        "aliases": _parse_json_list(p.aliases),
        "name_normalized": p.name_normalized,
        "scouting_notes": p.scouting_notes,
        # 所属履歴
        "team_history": _parse_json_list(p.team_history),
    }


@router.get("/players")
def list_players(request: Request, db: Session = Depends(get_db)):
    """選手一覧（試合数付き）。ロールに応じて閲覧範囲を制限する。"""
    ctx = get_auth(request)
    query = db.query(Player).order_by(Player.name)
    if ctx.is_player:
        # 選手は自分自身のPlayerレコードのみ
        if ctx.player_id:
            query = query.filter(Player.id == ctx.player_id)
        else:
            return {"success": True, "data": []}
    elif ctx.is_coach:
        # コーチは自チームの選手のみ
        team = (ctx.team_name or "").strip()
        if not team:
            return {"success": True, "data": []}
        query = query.filter(Player.team == team)
    # admin / analyst は全選手

    players = query.all()
    result = []
    for p in players:
        cnt = db.query(Match).filter(
            (Match.player_a_id == p.id) | (Match.player_b_id == p.id)
        ).count()
        result.append(player_to_dict(p, match_count=cnt))
    return {"success": True, "data": result}


@router.get("/players/search")
def search_players(q: str = "", db: Session = Depends(get_db)):
    """選手名検索（正規化・alias対応）クイックスタート用"""
    if not q or not q.strip():
        return {"success": True, "data": []}

    q_norm = normalize_name(q.strip())
    all_players = db.query(Player).order_by(Player.name).all()

    exact: list[Player] = []
    prefix: list[Player] = []
    contains: list[Player] = []
    alias_match: list[Player] = []

    for p in all_players:
        pn_norm = p.name_normalized or normalize_name(p.name)
        # 完全一致
        if pn_norm == q_norm:
            exact.append(p)
            continue
        # 前方一致
        if pn_norm.startswith(q_norm) or (p.name_en and normalize_name(p.name_en).startswith(q_norm)):
            prefix.append(p)
            continue
        # 部分一致
        if q_norm in pn_norm or (p.name_en and q_norm in normalize_name(p.name_en)):
            contains.append(p)
            continue
        # alias一致
        if p.aliases:
            try:
                aliases_list = json.loads(p.aliases)
                for alias in aliases_list:
                    if q_norm in normalize_name(alias):
                        alias_match.append(p)
                        break
            except Exception:
                pass

    ordered = exact + prefix + contains + alias_match
    # 重複除去（順序保持）
    seen: set[int] = set()
    result = []
    for p in ordered:
        if p.id not in seen:
            seen.add(p.id)
            cnt = db.query(Match).filter(
                (Match.player_a_id == p.id) | (Match.player_b_id == p.id)
            ).count()
            result.append(player_to_dict(p, match_count=cnt))

    return {"success": True, "data": result}


@router.get("/players/needs_review")
def list_needs_review(db: Session = Depends(get_db)):
    """要レビュー選手一覧（V4-U-003）"""
    players = db.query(Player).filter(Player.needs_review == True).order_by(Player.created_at.desc()).all()  # noqa: E712
    result = []
    for p in players:
        cnt = db.query(Match).filter(
            (Match.player_a_id == p.id) | (Match.player_b_id == p.id)
        ).count()
        result.append(player_to_dict(p, match_count=cnt))
    return {"success": True, "data": result}


@router.get("/players/teams")
def list_teams(db: Session = Depends(get_db)):
    """DBに登録済みの全チーム名を重複なしで返す（同姓同名識別・入力補完用）"""
    from sqlalchemy import distinct
    rows = (
        db.query(distinct(Player.team))
        .filter(Player.team.isnot(None), Player.team != "")
        .order_by(Player.team)
        .all()
    )
    teams = [row[0] for row in rows if row[0]]
    return {"success": True, "data": teams}


@router.post("/players", status_code=201)
def create_player(
    body: PlayerCreate,
    db: Session = Depends(get_db),
    _ctx=Depends(require_analyst),
):
    """選手登録"""
    data = body.model_dump()
    aliases = data.pop("aliases", None)
    aliases_json = json.dumps(aliases, ensure_ascii=False) if aliases else None
    # 正規化名を自動生成
    name_normalized = normalize_name(data["name"])

    player = Player(
        **data,
        aliases=aliases_json,
        name_normalized=name_normalized,
    )
    touch(player)
    db.add(player)
    db.commit()
    # 新規選手の登録はチーム可視範囲に影響し得るためグローバル無効化も実施
    response_cache.bump_players([player.id])
    response_cache.bump_version()
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
    from datetime import date as _date
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    # exclude_unset=True: クライアントが明示的に送ったフィールドのみ更新する
    # （exclude_none=True だと null 送信時に「クリア」ができない）
    data = body.model_dump(exclude_unset=True)

    # team 変更時: 旧チームを team_history に自動追記
    new_team = data.get("team")
    old_team = player.team
    if new_team is not None and old_team and old_team != new_team:
        history = _parse_json_list(player.team_history)
        until_str = _date.today().strftime("%Y-%m")
        # 同じチーム・同じ until の重複追記を防ぐ
        already = any(h.get("team") == old_team and h.get("until") == until_str for h in history)
        if not already:
            history.append({"team": old_team, "until": until_str, "note": ""})
        player.team_history = json.dumps(history, ensure_ascii=False)

    # aliases をJSON化
    if "aliases" in data:
        data["aliases"] = json.dumps(data["aliases"], ensure_ascii=False)
    # team_history を手動上書きする場合はJSON化
    if "team_history" in data:
        data["team_history"] = json.dumps(
            [e.model_dump() for e in body.team_history],  # type: ignore[union-attr]
            ensure_ascii=False,
        )
    # name 変更時に name_normalized を更新
    if "name" in data:
        data["name_normalized"] = normalize_name(data["name"])
    for key, value in data.items():
        setattr(player, key, value)
    touch(player)
    db.commit()
    # 選手単位で無効化 + team 変更はコーチ可視範囲に影響するためグローバルも無効化
    response_cache.bump_players([player_id])
    response_cache.bump_version()
    db.refresh(player)
    return {"success": True, "data": player_to_dict(player)}


@router.delete("/players/{player_id}")
def delete_player(
    player_id: int,
    db: Session = Depends(get_db),
    _ctx=Depends(require_analyst),
):
    """選手削除"""
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    # 試合に紐づいているか確認
    ref_count = db.query(Match).filter(
        (Match.player_a_id == player_id) |
        (Match.player_b_id == player_id) |
        (Match.partner_a_id == player_id) |
        (Match.partner_b_id == player_id)
    ).count()
    if ref_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"この選手は {ref_count} 件の試合に紐づいているため削除できません。先に試合を削除してください。"
        )
    db.delete(player)
    db.commit()
    # 削除は全選手への可視範囲影響もあるためグローバル + 自身の両方無効化
    response_cache.bump_players([player_id])
    response_cache.bump_version()
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
