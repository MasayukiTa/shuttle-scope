"""試合管理API（/api/matches）"""
import asyncio
import json
import re
import unicodedata
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, Player, GameSet, Rally
from backend.utils.video_downloader import video_downloader

router = APIRouter()


class MatchCreate(BaseModel):
    tournament: str
    tournament_level: str
    tournament_grade: Optional[str] = None
    round: str
    date: date
    venue: Optional[str] = None
    format: str
    player_a_id: int
    player_b_id: int
    partner_a_id: Optional[int] = None
    partner_b_id: Optional[int] = None
    result: str
    final_score: Optional[str] = None
    video_url: Optional[str] = None
    notes: Optional[str] = None
    # V4
    initial_server: Optional[str] = None
    competition_type: Optional[str] = "unknown"
    created_via_quick_start: bool = False
    metadata_status: Optional[str] = "minimal"


class MatchUpdate(BaseModel):
    tournament: Optional[str] = None
    tournament_level: Optional[str] = None
    tournament_grade: Optional[str] = None
    round: Optional[str] = None
    date: Optional[date] = None
    venue: Optional[str] = None
    format: Optional[str] = None
    result: Optional[str] = None
    final_score: Optional[str] = None
    video_url: Optional[str] = None
    video_local_path: Optional[str] = None
    annotation_status: Optional[str] = None
    notes: Optional[str] = None
    # V4
    initial_server: Optional[str] = None
    competition_type: Optional[str] = None
    metadata_status: Optional[str] = None
    exception_reason: Optional[str] = None


def match_to_dict(m: Match, include_players: bool = True, db: Session = None) -> dict:
    d = {
        "id": m.id,
        "tournament": m.tournament,
        "tournament_level": m.tournament_level,
        "tournament_grade": m.tournament_grade,
        "round": m.round,
        "date": m.date.isoformat() if m.date else None,
        "venue": m.venue,
        "format": m.format,
        "player_a_id": m.player_a_id,
        "player_b_id": m.player_b_id,
        "partner_a_id": m.partner_a_id,
        "partner_b_id": m.partner_b_id,
        "result": m.result,
        "final_score": m.final_score,
        "video_url": m.video_url,
        "video_local_path": m.video_local_path,
        "video_quality": m.video_quality,
        "camera_angle": m.camera_angle,
        "annotator_id": m.annotator_id,
        "annotation_status": m.annotation_status,
        "annotation_progress": m.annotation_progress,
        "notes": m.notes,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        # V4
        "initial_server": m.initial_server,
        "competition_type": m.competition_type or "unknown",
        "created_via_quick_start": bool(m.created_via_quick_start),
        "metadata_status": m.metadata_status or "minimal",
        "exception_reason": m.exception_reason,
    }
    if include_players and db:
        pa = db.get(Player, m.player_a_id)
        pb = db.get(Player, m.player_b_id)
        d["player_a"] = {"id": pa.id, "name": pa.name, "team": pa.team} if pa else None
        d["player_b"] = {"id": pb.id, "name": pb.name, "team": pb.team} if pb else None
        if m.partner_a_id:
            ppa = db.get(Player, m.partner_a_id)
            d["partner_a"] = {"id": ppa.id, "name": ppa.name, "team": ppa.team} if ppa else None
        else:
            d["partner_a"] = None
        if m.partner_b_id:
            ppb = db.get(Player, m.partner_b_id)
            d["partner_b"] = {"id": ppb.id, "name": ppb.name, "team": ppb.team} if ppb else None
        else:
            d["partner_b"] = None
    return d


@router.get("/matches")
def list_matches(
    player_id: Optional[int] = None,
    tournament_level: Optional[str] = None,
    year: Optional[int] = None,
    incomplete_only: bool = False,
    db: Session = Depends(get_db),
):
    """試合一覧（フィルタ付き）"""
    query = db.query(Match)
    if player_id:
        query = query.filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
    if tournament_level:
        query = query.filter(Match.tournament_level == tournament_level)
    if year:
        query = query.filter(Match.date >= date(year, 1, 1), Match.date <= date(year, 12, 31))
    if incomplete_only:
        query = query.filter(Match.annotation_status != "complete")
    matches = query.order_by(Match.date.desc()).all()
    return {"success": True, "data": [match_to_dict(m, include_players=True, db=db) for m in matches]}


@router.post("/matches", status_code=201)
def create_match(body: MatchCreate, db: Session = Depends(get_db)):
    """試合登録"""
    match = Match(**body.model_dump())
    db.add(match)
    db.commit()
    db.refresh(match)
    return {"success": True, "data": match_to_dict(match, include_players=True, db=db)}


@router.get("/matches/{match_id}")
def get_match(match_id: int, db: Session = Depends(get_db)):
    """試合詳細"""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    return {"success": True, "data": match_to_dict(match, include_players=True, db=db)}


@router.put("/matches/{match_id}")
def update_match(match_id: int, body: MatchUpdate, db: Session = Depends(get_db)):
    """試合更新"""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(match, key, value)
    db.commit()
    db.refresh(match)
    return {"success": True, "data": match_to_dict(match, include_players=True, db=db)}


@router.delete("/matches/{match_id}")
def delete_match(match_id: int, db: Session = Depends(get_db)):
    """試合削除"""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    db.delete(match)
    db.commit()
    return {"success": True, "data": {"id": match_id}}


class QuickStartBody(BaseModel):
    """クイックスタート専用リクエスト（V4）"""
    player_a_id: int                           # 自チーム選手（登録済み）
    opponent_name: str                         # 相手選手名（新規または既存）
    opponent_id: Optional[int] = None          # 既存選手を選択した場合はIDを指定
    opponent_team: Optional[str] = None        # 相手選手チーム名（同姓同名識別用）
    initial_server: Optional[str] = None       # player_a / player_b
    competition_type: str = "unknown"          # official/practice_match/open_practice/unknown
    tournament: Optional[str] = None           # 大会名（任意）
    round: Optional[str] = None               # ラウンド（任意）
    format: str = "singles"


def _normalize_name(name: str) -> str:
    n = unicodedata.normalize("NFKC", name).lower()
    return re.sub(r"[\s\-_.・]", "", n)


@router.post("/matches/quick-start", status_code=201)
def quick_start_match(body: QuickStartBody, db: Session = Depends(get_db)):
    """クイックスタート: 相手選手auto-create + 試合作成を一括実行（V4）"""
    # 自チーム選手確認
    player_a = db.get(Player, body.player_a_id)
    if not player_a:
        raise HTTPException(status_code=404, detail="自チーム選手が見つかりません")

    # 相手選手の解決
    if body.opponent_id:
        player_b = db.get(Player, body.opponent_id)
        if not player_b:
            raise HTTPException(status_code=404, detail="指定された相手選手が見つかりません")
    else:
        # 相手選手を暫定作成（provisional）
        name_normalized = _normalize_name(body.opponent_name)
        player_b = Player(
            name=body.opponent_name,
            name_normalized=name_normalized,
            team=body.opponent_team or None,    # チーム名（同姓同名識別用）
            is_target=False,
            dominant_hand=None,
            profile_status="provisional",
            needs_review=True,
            created_via_quick_start=True,
        )
        db.add(player_b)
        db.flush()  # IDを確定させる

    today = date.today()
    match = Match(
        tournament=body.tournament or "未設定",
        tournament_level="その他",
        round=body.round or "未設定",
        date=today,
        format=body.format,
        player_a_id=body.player_a_id,
        player_b_id=player_b.id,
        result="unfinished",
        initial_server=body.initial_server,
        competition_type=body.competition_type,
        created_via_quick_start=True,
        metadata_status="minimal",
        annotation_status="in_progress",
    )
    db.add(match)
    db.commit()
    db.refresh(match)
    db.refresh(player_b)

    return {
        "success": True,
        "data": {
            "match": match_to_dict(match, include_players=True, db=db),
            "opponent_created": body.opponent_id is None,
        },
    }


@router.get("/matches/needs_review")
def list_needs_review_matches(db: Session = Depends(get_db)):
    """要レビュー試合一覧（V4-U-003）"""
    matches = db.query(Match).filter(
        Match.metadata_status != "verified"
    ).order_by(Match.created_at.desc()).all()
    return {"success": True, "data": [match_to_dict(m, include_players=True, db=db) for m in matches]}


@router.get("/matches/{match_id}/rallies")
def get_match_rallies(match_id: int, db: Session = Depends(get_db)):
    """試合のラリー一覧"""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    sets = db.query(GameSet).filter(GameSet.match_id == match_id).order_by(GameSet.set_num).all()
    result = []
    for s in sets:
        rallies = db.query(Rally).filter(Rally.set_id == s.id).order_by(Rally.rally_num).all()
        for r in rallies:
            result.append({
                "id": r.id,
                "set_num": s.set_num,
                "rally_num": r.rally_num,
                "server": r.server,
                "winner": r.winner,
                "end_type": r.end_type,
                "rally_length": r.rally_length,
                "score_a_after": r.score_a_after,
                "score_b_after": r.score_b_after,
            })
    return {"success": True, "data": result}


class DownloadRequest(BaseModel):
    quality: str = "720"        # "360" / "480" / "720" / "1080" / "best"
    cookie_browser: str = ""    # "" / "chrome" / "edge" / "firefox" / "brave" / "opera" / ...


@router.post("/matches/{match_id}/download")
async def start_download(
    match_id: int,
    body: DownloadRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """配信動画ダウンロード開始（yt-dlp）
    cookie_browser を指定するとそのブラウザの Cookie を使ってログイン認証を通過する。
    """
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    if not match.video_url:
        raise HTTPException(status_code=400, detail="動画URLが設定されていません")

    job_id = video_downloader.create_job_id()
    background_tasks.add_task(
        video_downloader.start_download,
        match.video_url,
        job_id,
        body.quality,
        body.cookie_browser,
    )
    return {"success": True, "data": {"job_id": job_id}}


@router.get("/matches/{match_id}/download/status")
def get_download_status(match_id: int, job_id: str, db: Session = Depends(get_db)):
    """ダウンロード進捗確認"""
    progress = video_downloader.get_progress(job_id)
    # ダウンロード完了時は試合レコードのパスを更新
    if progress.get("status") == "complete" and progress.get("filepath"):
        match = db.get(Match, match_id)
        if match:
            match.video_local_path = progress["filepath"]
            db.commit()
    return {"success": True, "data": progress}
