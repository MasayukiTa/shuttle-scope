"""試合管理API（/api/matches）"""
import asyncio
import json
import re
import unicodedata
from datetime import date as _date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, Player, GameSet, Rally, MatchCVArtifact
from backend.utils.video_downloader import video_downloader
from backend.utils import response_cache
from backend.utils.sync_meta import touch
from backend.utils.auth import get_auth

router = APIRouter()


class MatchCreate(BaseModel):
    tournament: str
    tournament_level: str
    tournament_grade: Optional[str] = None
    round: str
    date: _date
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
    date: Optional[_date] = None
    venue: Optional[str] = None
    format: Optional[str] = None
    player_a_id: Optional[int] = None
    player_b_id: Optional[int] = None
    partner_a_id: Optional[int] = None
    partner_b_id: Optional[int] = None
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


def _effective_status(
    m: Match,
    db: Optional[Session],
    *,
    has_sets_ids: Optional[set] = None,
    has_cv_ids: Optional[set] = None,
) -> str:
    """作業中判定: 完了・確認済みはそのまま返す。
    それ以外はセット/CV artifact の存在を確認し、痕跡があれば in_progress、なければ pending。
    list_matches など大量マッチを返すエンドポイントでは has_sets_ids/has_cv_ids を事前集計して
    per-match の N+1 クエリを回避する。
    """
    stored = m.annotation_status or "pending"
    if stored in ("complete", "reviewed"):
        return stored
    if has_sets_ids is not None or has_cv_ids is not None:
        if has_sets_ids and m.id in has_sets_ids:
            return "in_progress"
        if has_cv_ids and m.id in has_cv_ids:
            return "in_progress"
        return "pending"
    if db is None:
        return stored
    has_sets = db.query(GameSet.id).filter(GameSet.match_id == m.id).first() is not None
    if has_sets:
        return "in_progress"
    has_cv = db.query(MatchCVArtifact.id).filter(MatchCVArtifact.match_id == m.id).first() is not None
    if has_cv:
        return "in_progress"
    return "pending"


def match_to_dict(
    m: Match,
    include_players: bool = True,
    db: Session = None,
    *,
    player_map: Optional[dict] = None,
    has_sets_ids: Optional[set] = None,
    has_cv_ids: Optional[set] = None,
) -> dict:
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
        "annotation_status": _effective_status(m, db, has_sets_ids=has_sets_ids, has_cv_ids=has_cv_ids),
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
    if include_players and (db or player_map is not None):
        def _lookup(pid):
            if pid is None:
                return None
            if player_map is not None:
                return player_map.get(pid)
            return db.get(Player, pid)
        pa = _lookup(m.player_a_id)
        pb = _lookup(m.player_b_id)
        d["player_a"] = {"id": pa.id, "name": pa.name, "team": pa.team} if pa else None
        d["player_b"] = {"id": pb.id, "name": pb.name, "team": pb.team} if pb else None
        ppa = _lookup(m.partner_a_id) if m.partner_a_id else None
        d["partner_a"] = {"id": ppa.id, "name": ppa.name, "team": ppa.team} if ppa else None
        ppb = _lookup(m.partner_b_id) if m.partner_b_id else None
        d["partner_b"] = {"id": ppb.id, "name": ppb.name, "team": ppb.team} if ppb else None
    return d


def _bulk_match_context(matches: list, db: Session) -> dict:
    """list_matches/list_needs_review_matches 用: 全マッチぶんの Player / status 情報を
    バルクロードして per-match N+1 を排除する。"""
    if not matches:
        return {"player_map": {}, "has_sets_ids": set(), "has_cv_ids": set()}
    pids = set()
    mids = [m.id for m in matches]
    for m in matches:
        for pid in (m.player_a_id, m.player_b_id, m.partner_a_id, m.partner_b_id):
            if pid:
                pids.add(pid)
    player_rows = db.query(Player).filter(Player.id.in_(pids)).all() if pids else []
    player_map = {p.id: p for p in player_rows}
    sets_rows = db.query(GameSet.match_id).filter(GameSet.match_id.in_(mids)).distinct().all()
    has_sets_ids = {r[0] for r in sets_rows}
    cv_rows = db.query(MatchCVArtifact.match_id).filter(MatchCVArtifact.match_id.in_(mids)).distinct().all()
    has_cv_ids = {r[0] for r in cv_rows}
    return {"player_map": player_map, "has_sets_ids": has_sets_ids, "has_cv_ids": has_cv_ids}


@router.get("/matches")
def list_matches(
    request: Request,
    player_id: Optional[int] = None,
    tournament_level: Optional[str] = None,
    year: Optional[int] = None,
    incomplete_only: bool = False,
    db: Session = Depends(get_db),
):
    """試合一覧（フィルタ付き）

    role=player 時は X-Player-Id に関与する試合のみを返す（ダブルスの partner も含む4役）。
    ID 書き換えで他選手データを覗く攻撃に対する多層防御。
    """
    ctx = get_auth(request)
    query = db.query(Match)

    # role=player → 自身が関与する試合のみに強制的に絞り込み
    if ctx.is_player:
        if not ctx.player_id:
            return {"success": True, "data": []}
        pid = ctx.player_id
        query = query.filter(or_(
            Match.player_a_id  == pid,
            Match.partner_a_id == pid,
            Match.player_b_id  == pid,
            Match.partner_b_id == pid,
        ))
    # role=coach → 自チーム選手がどちらかのサイドに登録されている試合のみ
    elif ctx.is_coach:
        if not ctx.team_name:
            return {"success": True, "data": []}
        team_player_ids = [p.id for p in db.query(Player.id).filter(Player.team == ctx.team_name).all()]
        if not team_player_ids:
            return {"success": True, "data": []}
        query = query.filter(or_(
            Match.player_a_id.in_(team_player_ids),
            Match.partner_a_id.in_(team_player_ids),
            Match.player_b_id.in_(team_player_ids),
            Match.partner_b_id.in_(team_player_ids),
        ))
    elif player_id:
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
    ctx_bulk = _bulk_match_context(matches, db)

    def _result_for(m: Match) -> str | None:
        """player ロール時、B サイド選手なら result を反転して返す。"""
        r = m.result
        if ctx.is_player and ctx.player_id and r in ("win", "loss"):
            if ctx.player_id in {m.player_b_id, m.partner_b_id}:
                return "loss" if r == "win" else "win"
        return r

    result = []
    for m in matches:
        d = match_to_dict(m, include_players=True, db=db, **ctx_bulk)
        d["result"] = _result_for(m)
        result.append(d)
    return {"success": True, "data": result}


@router.post("/matches", status_code=201)
def create_match(body: MatchCreate, request: Request, db: Session = Depends(get_db)):
    """試合登録"""
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    match = Match(**body.model_dump())
    touch(match)
    db.add(match)
    db.commit()
    # 関与選手4枠のキャッシュのみ無効化（他選手の解析キャッシュは生かす）
    response_cache.bump_players([
        body.player_a_id, body.player_b_id,
        getattr(body, "partner_a_id", None), getattr(body, "partner_b_id", None),
    ])
    db.refresh(match)
    return {"success": True, "data": match_to_dict(match, include_players=True, db=db)}


@router.get("/matches/needs_review")
def list_needs_review_matches(request: Request, db: Session = Depends(get_db)):
    """要レビュー試合一覧（V4-U-003）— {match_id} より前に定義が必要"""
    ctx = get_auth(request)
    q = db.query(Match).filter(Match.metadata_status != "verified")
    if ctx.is_player:
        if not ctx.player_id:
            return {"success": True, "data": []}
        pid = ctx.player_id
        q = q.filter(or_(
            Match.player_a_id  == pid,
            Match.partner_a_id == pid,
            Match.player_b_id  == pid,
            Match.partner_b_id == pid,
        ))
    matches = q.order_by(Match.created_at.desc()).all()
    ctx_bulk = _bulk_match_context(matches, db)
    return {"success": True, "data": [
        match_to_dict(m, include_players=True, db=db, **ctx_bulk) for m in matches
    ]}


@router.get("/matches/{match_id}")
def get_match(match_id: int, db: Session = Depends(get_db)):
    """試合詳細"""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    return {"success": True, "data": match_to_dict(match, include_players=True, db=db)}


@router.put("/matches/{match_id}")
def update_match(match_id: int, body: MatchUpdate, request: Request, db: Session = Depends(get_db)):
    """試合更新"""
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    # 更新前の関与選手を退避（選手差し替えの場合、旧選手のキャッシュも無効化が必要）
    pre_players = [match.player_a_id, match.player_b_id, match.partner_a_id, match.partner_b_id]
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(match, key, value)
    touch(match)
    db.commit()
    post_players = [match.player_a_id, match.player_b_id, match.partner_a_id, match.partner_b_id]
    response_cache.bump_players(pre_players + post_players)
    db.refresh(match)
    return {"success": True, "data": match_to_dict(match, include_players=True, db=db)}


@router.delete("/matches/{match_id}")
def delete_match(match_id: int, request: Request, db: Session = Depends(get_db)):
    """試合削除"""
    ctx = get_auth(request)
    if not (ctx.is_admin or ctx.is_analyst):
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    # 削除前に関与選手を控えておく（削除後は辿れないため）
    affected_players = [match.player_a_id, match.player_b_id, match.partner_a_id, match.partner_b_id]
    db.delete(match)
    db.commit()
    response_cache.bump_players(affected_players)
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
def quick_start_match(body: QuickStartBody, request: Request, db: Session = Depends(get_db)):
    """クイックスタート: 相手選手auto-create + 試合作成を一括実行（V4）"""
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
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
            dominant_hand="unknown",
            profile_status="provisional",
            needs_review=True,
            created_via_quick_start=True,
        )
        db.add(player_b)
        db.flush()  # IDを確定させる

    today = _date.today()
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
    # クイックスタートで関与する2選手だけ無効化
    response_cache.bump_players([body.player_a_id, player_b.id])
    db.refresh(match)
    db.refresh(player_b)

    return {
        "success": True,
        "data": {
            "match": match_to_dict(match, include_players=True, db=db),
            "opponent_created": body.opponent_id is None,
        },
    }


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
                "score_a_before": r.score_a_before,
                "score_b_before": r.score_b_before,
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
            # 動画ローカルパスは解析結果に影響しないためキャッシュ無効化は行わない
    return {"success": True, "data": progress}
