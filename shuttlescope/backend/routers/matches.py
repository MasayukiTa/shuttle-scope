"""試合管理API（/api/matches）"""
import asyncio
import json
import re
import unicodedata
import uuid
from datetime import date as _date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, Player, GameSet, Rally, MatchCVArtifact
from backend.utils.video_downloader import video_downloader
from backend.utils import response_cache
from backend.utils.sync_meta import touch
from backend.utils.auth import (
    get_auth,
    apply_match_team_scope,
    user_can_access_match,
    resolve_owner_team_for_match_create,
)

router = APIRouter()


class MatchCreate(BaseModel):
    model_config = {"extra": "forbid"}
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
    annotation_status: Optional[str] = None
    # Phase B-5: チーム境界（admin のみ owner_team_id/is_public_pool を指定可能。
    # coach/analyst の指定はサーバ側で無視され、ctx.team_id が強制される）
    owner_team_id: Optional[int] = None
    is_public_pool: bool = False
    home_team_id: Optional[int] = None
    away_team_id: Optional[int] = None


class MatchUpdate(BaseModel):
    # 未知フィールドの silent drop を禁止 (id / created_at / updated_at 等の内部
    # フィールドを body 注入する mass assignment を明示拒否)
    model_config = {"extra": "forbid"}
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
    # Phase B-5: admin のみ変更可
    owner_team_id: Optional[int] = None
    is_public_pool: Optional[bool] = None
    home_team_id: Optional[int] = None
    away_team_id: Optional[int] = None


# ビジネスロジック用 enum (config.py で定義された値と一致)
_MATCH_RESULT_ALLOWED = {"win", "loss", "draw", "unknown"}
_MATCH_FORMAT_ALLOWED = {"singles", "doubles", "mixed"}
_MATCH_TOURNAMENT_LEVELS = {"IC", "IS", "SJL", "全日本", "国内", "その他"}
_MATCH_ANNOTATION_STATUS = {"not_started", "in_progress", "complete", "reviewed"}


def _validate_match_player_refs(body: "MatchUpdate | MatchCreate", db: Session, *, match: Optional[Match] = None) -> None:
    """match の player_a/b_id, partner_a/b_id が実在する player を指しているか検証。

    referential integrity 破壊 (0/-1/存在しない ID の注入) を 422 で拒否する。
    さらに論理整合性: A 側と B 側が同じ player / partner 重複も拒否。
    """
    for field in ("player_a_id", "player_b_id", "partner_a_id", "partner_b_id"):
        pid = getattr(body, field, None)
        if pid is None:
            continue
        if not isinstance(pid, int):
            raise HTTPException(status_code=422, detail=f"{field} must be an integer")
        if pid <= 0 or pid > 2**31 - 1:
            raise HTTPException(status_code=422, detail=f"{field} out of range")
        if not db.get(Player, pid):
            raise HTTPException(status_code=422, detail=f"{field}={pid} does not exist")

    # 論理整合性: 同じ player が A 側と B 側に両方現れない
    # (既存レコードとマージした最終値で判定)
    final_a = getattr(body, "player_a_id", None) or (match.player_a_id if match else None)
    final_b = getattr(body, "player_b_id", None) or (match.player_b_id if match else None)
    final_pa = getattr(body, "partner_a_id", None) or (match.partner_a_id if match else None)
    final_pb = getattr(body, "partner_b_id", None) or (match.partner_b_id if match else None)
    a_side = {p for p in (final_a, final_pa) if p}
    b_side = {p for p in (final_b, final_pb) if p}
    overlap = a_side & b_side
    if overlap:
        raise HTTPException(status_code=422, detail=f"same player on both sides: {sorted(overlap)}")
    # 同サイド内重複 (player_a == partner_a 等)
    if final_a and final_pa and final_a == final_pa:
        raise HTTPException(status_code=422, detail="player_a_id and partner_a_id must differ")
    if final_b and final_pb and final_b == final_pb:
        raise HTTPException(status_code=422, detail="player_b_id and partner_b_id must differ")


def _validate_match_enums(body: "MatchUpdate | MatchCreate") -> None:
    """match の enum フィールドに不正な値が入っていないか検証。

    DB 整合性破壊 (result=long string, tournament_level=invalid など) を 422 で拒否する。
    """
    # result / format は DB 側 NOT NULL なので MatchUpdate でも
    # 明示的な null は 422 で拒否する（フィールド未指定は exclude_unset=True で
    # setattr をスキップできるが、明示 null は setattr(match.result, None) で
    # DB IntegrityError になる）
    is_update = isinstance(body, MatchUpdate)
    if "result" in body.model_fields_set:
        if body.result is None:
            raise HTTPException(status_code=422, detail="result は null にできません")
        if body.result not in _MATCH_RESULT_ALLOWED:
            raise HTTPException(status_code=422, detail=f"invalid result: {body.result!r}")
    elif not is_update and body.result not in _MATCH_RESULT_ALLOWED:
        raise HTTPException(status_code=422, detail=f"invalid result: {body.result!r}")
    if "format" in body.model_fields_set:
        if body.format is None:
            raise HTTPException(status_code=422, detail="format は null にできません")
        if body.format not in _MATCH_FORMAT_ALLOWED:
            raise HTTPException(status_code=422, detail=f"invalid format: {body.format!r}")
    elif not is_update and body.format not in _MATCH_FORMAT_ALLOWED:
        raise HTTPException(status_code=422, detail=f"invalid format: {body.format!r}")
    if body.tournament_level is not None and body.tournament_level not in _MATCH_TOURNAMENT_LEVELS:
        raise HTTPException(status_code=422, detail=f"invalid tournament_level: {body.tournament_level!r}")
    # date の範囲検証 (0001-01-01 / 9999-12-31 等の無意味な値を拒否)
    # バドミントン BWF は 1934 年設立、選手の出場年月日が記録されるのは 1970 年以降
    # 未来は 2 年先まで (次シーズンのスケジュール登録用)
    from datetime import date as _d_m, timedelta as _td_m
    if body.date is not None:
        today = _d_m.today()
        if body.date < _d_m(1970, 1, 1) or body.date > today + _td_m(days=365 * 2):
            raise HTTPException(
                status_code=422,
                detail=f"date out of range (1970-01-01 to {today + _td_m(days=365*2)})",
            )
    if getattr(body, "annotation_status", None) is not None and body.annotation_status not in _MATCH_ANNOTATION_STATUS:
        raise HTTPException(status_code=422, detail=f"invalid annotation_status: {body.annotation_status!r}")
    # 文字列フィールドの長さ上限 + 制御文字 (CR/LF/NUL) 拒否
    # null byte / CRLF 埋め込みはログ偽装・DB 処理バグ・UI 表示汚染経路
    import re as _re_ctl
    # tournament / round は業務上必須 (空/空白のみ禁止)。無意味な DB 肥大を防ぐ。
    _non_empty_required = {"tournament", "round"}
    for fname, maxlen in (
        ("tournament", 200), ("tournament_grade", 100), ("round", 100),
        ("venue", 200), ("notes", 5000), ("final_score", 200),
        ("initial_server", 50), ("competition_type", 50),
        ("metadata_status", 50), ("exception_reason", 500),
    ):
        v = getattr(body, fname, None)
        if v is None:
            continue
        if not isinstance(v, str):
            continue
        if len(v) > maxlen:
            raise HTTPException(status_code=422, detail=f"{fname} too long (max {maxlen})")
        if _re_ctl.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", v):
            raise HTTPException(status_code=422, detail=f"{fname} contains control characters")
        if fname in _non_empty_required and not v.strip():
            raise HTTPException(status_code=422, detail=f"{fname} must not be empty or whitespace only")
    # video_url の制御文字拒否 (CR/LF/Tab 埋め込みで header injection / shell 攻撃経路)
    vu = getattr(body, "video_url", None)
    if vu is not None and isinstance(vu, str) and vu != "":
        if len(vu) > 2000:
            raise HTTPException(status_code=422, detail="video_url too long (max 2000)")
        import re as _re_vu
        if _re_vu.search(r"[\x00-\x1f\x7f]", vu):
            raise HTTPException(status_code=422, detail="video_url contains control characters")
        if vu.strip() != vu:
            raise HTTPException(status_code=422, detail="video_url must not have leading/trailing whitespace")
        # URL スキーム検証: javascript: / data: / about: / mailto: / file: / ftp:
        # 等の stored XSS 経路や SSRF 原資を PUT/POST 時点で拒否する。
        # validate_external_url は download 時のみ呼ばれるため、DB には格納されてしまう。
        # React が href に出力する際の XSS を防ぐため、ここで URL scheme をチェック。
        low = vu.lower().lstrip()
        for bad_scheme in ("javascript:", "data:", "vbscript:", "file:", "about:", "mailto:",
                           "tel:", "jar:", "feed:", "view-source:", "chrome:", "chrome-extension:",
                           "resource:", "ms-appx:", "ms-appdata:", "blob:", "filesystem:"):
            if low.startswith(bad_scheme):
                raise HTTPException(
                    status_code=422,
                    detail=f"video_url scheme {bad_scheme!r} is not allowed",
                )
        # http/https 以外を拒否
        if not (low.startswith("http://") or low.startswith("https://")):
            raise HTTPException(
                status_code=422,
                detail="video_url must start with http:// or https://",
            )
    # video_local_path の path traversal 防御
    # `server://{upload_id}` または絶対 / 相対パスのいずれでも、`..` / null / 制御文字を拒否
    vlp = getattr(body, "video_local_path", None)
    if vlp is not None and isinstance(vlp, str):
        if len(vlp) > 1000:
            raise HTTPException(status_code=422, detail="video_local_path too long (max 1000)")
        import re as _re_vlp
        if _re_vlp.search(r"[\x00-\x1f\x7f]", vlp):
            raise HTTPException(status_code=422, detail="video_local_path contains control characters")
        # path traversal 拒否: `..` `//` `\\..\\` 等
        if ".." in vlp or "\\.." in vlp or "/.." in vlp:
            raise HTTPException(status_code=422, detail="video_local_path contains path traversal")
        # 受理する形式は `server://{uuid}{ext}` または `localfile://...` のみ (プロトコル以外はアプリ実装で未使用)
        if not (vlp.startswith("server://") or vlp.startswith("localfile://") or vlp == ""):
            raise HTTPException(status_code=422, detail="video_local_path must be server:// or localfile:// scheme")
    # notes / final_score / tournament / venue の HTML タグ / script 拒否 (stored XSS 対策)
    # 試合表示画面で出力される文字列は全て HTML タグをブロック
    import re as _re_xss_m
    _XSS_RE = _re_xss_m.compile(
        r"</?(script|iframe|object|embed|svg|style|link|meta|form|img[^>]*on\w+)[\s>/]",
        _re_xss_m.IGNORECASE,
    )
    for fname in ("notes", "final_score", "tournament", "venue", "round", "tournament_grade", "exception_reason"):
        v = getattr(body, fname, None)
        if v is not None and isinstance(v, str) and _XSS_RE.search(v):
            raise HTTPException(status_code=422, detail=f"{fname} contains disallowed HTML tags")


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
        # Phase B: チーム境界情報
        "owner_team_id": m.owner_team_id,
        "is_public_pool": bool(getattr(m, "is_public_pool", False)),
        "home_team_id": getattr(m, "home_team_id", None),
        "away_team_id": getattr(m, "away_team_id", None),
    }
    # owner team の display_id / 表示名を補助フィールドとして添える
    if db is not None and m.owner_team_id is not None:
        from backend.db.models import Team as _Team
        ot = db.get(_Team, m.owner_team_id)
        if ot is not None:
            d["owner_team_display_id"] = ot.display_id
            d["owner_team_display_name"] = ot.name
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
    player_id: Optional[int] = Query(default=None, ge=1, le=2**31 - 1),
    tournament_level: Optional[str] = Query(default=None, max_length=50),
    year: Optional[int] = Query(default=None, ge=1900, le=2100),
    incomplete_only: bool = False,
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """試合一覧（フィルタ付き）。

    Query バリデーション (year 1900-2100 / limit 1-2000 / player_id positive int)
    で `year=-1` 等の 500 エラーと `limit=-1` の全件取得 exfil を遮断する。

    role=player 時は X-Player-Id に関与する試合のみを返す（ダブルスの partner も含む4役）。
    ID 書き換えで他選手データを覗く攻撃に対する多層防御。
    """
    # player_id が指定された場合、実在する player か事前確認 (9999999 等の適当 ID で
    # 「該当なし」結果を取得して内部構造を推測される攻撃を早期 422 で閉じる)
    if player_id is not None and not db.get(Player, player_id):
        raise HTTPException(status_code=422, detail=f"player_id={player_id} does not exist")
    ctx = get_auth(request)
    query = db.query(Match)

    # Phase B-6: チーム境界フィルタを統一適用（admin は素通し、player は自身関与のみ、
    # coach/analyst は owner / public / 自チーム選手登場 のいずれか）
    query = apply_match_team_scope(query, ctx)

    if player_id and not ctx.is_player:
        query = query.filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
    if tournament_level:
        query = query.filter(Match.tournament_level == tournament_level)
    if year:
        query = query.filter(Match.date >= date(year, 1, 1), Match.date <= date(year, 12, 31))
    if incomplete_only:
        query = query.filter(Match.annotation_status != "complete")
    matches = query.order_by(Match.date.desc()).limit(limit).all()
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
    """試合登録

    Phase B-5: owner_team_id / is_public_pool は admin のみ自由設定可。
    coach/analyst の場合は ctx.team_id を強制注入し、is_public_pool は False に。
    """
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    _validate_match_enums(body)
    _validate_match_player_refs(body, db)
    # analyst/coach は自チーム選手が含まれる試合のみ作成可能 (cross-team データ汚染防止)
    if not ctx.is_admin:
        team = (ctx.team_name or "").strip()
        if not team:
            from backend.utils.control_plane import allow_legacy_header_auth
            if not allow_legacy_header_auth(request):
                raise HTTPException(status_code=403, detail="team_name 未設定")
        else:
            pids = [p for p in (body.player_a_id, body.player_b_id,
                                getattr(body, "partner_a_id", None),
                                getattr(body, "partner_b_id", None)) if p]
            if pids:
                team_players = db.query(Player).filter(Player.id.in_(pids)).all()
                if not any((p.team or "").strip() == team for p in team_players):
                    raise HTTPException(
                        status_code=403,
                        detail=f"自チーム ({team}) の選手が含まれない試合は作成できません",
                    )
    # Phase B-5: owner_team_id / is_public_pool を解決
    owner_id, is_public = resolve_owner_team_for_match_create(
        ctx,
        requested_team_id=body.owner_team_id,
        requested_is_public_pool=body.is_public_pool,
    )
    payload = body.model_dump()
    payload["owner_team_id"] = owner_id
    payload["is_public_pool"] = is_public
    match = Match(**payload)
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
    # Phase B-6: チーム境界フィルタを統一適用
    q = apply_match_team_scope(q, ctx)
    matches = q.order_by(Match.created_at.desc()).all()
    ctx_bulk = _bulk_match_context(matches, db)
    return {"success": True, "data": [
        match_to_dict(m, include_players=True, db=db, **ctx_bulk) for m in matches
    ]}


@router.get("/matches/{match_id}")
def get_match(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """試合詳細 (BOLA/IDOR: ロール別スコープ検証 + Phase B-6 チーム境界)。
    match_id は 32bit 正整数に制限 (int overflow で 500 が返る経路を遮断)。
    """
    if match_id <= 0 or match_id > 2**31 - 1:
        raise HTTPException(status_code=422, detail="match_id out of range")
    ctx = get_auth(request)
    match = db.get(Match, match_id)
    if not match or not user_can_access_match(ctx, match):
        # 存在自体を隠す（403 ではなく 404）
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    # player/coach は require_match_scope で自分/自チームに関わる試合のみ許可
    from backend.utils.auth import require_match_scope
    require_match_scope(request, match, db)
    return {"success": True, "data": match_to_dict(match, include_players=True, db=db)}


@router.put("/matches/{match_id}")
def update_match(match_id: int, body: MatchUpdate, request: Request, db: Session = Depends(get_db)):
    """試合更新 (admin/analyst/coach)。全変更を audit log に記録する。"""
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    _validate_match_enums(body)
    # 既存レコードを取得してから player refs を検証 (merged state で論理整合性確認)
    match = db.get(Match, match_id)
    if not match or not user_can_access_match(ctx, match):
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    # analyst/coach は自チーム scope のみ更新可 (cross-team 改竄防止)
    from backend.utils.auth import require_match_scope as _rms
    _rms(request, match, db)
    _validate_match_player_refs(body, db, match=match)
    # Phase B-5: owner / public / home / away の変更は admin のみ
    payload = body.model_dump(exclude_unset=True)
    privileged_keys = {"owner_team_id", "is_public_pool", "home_team_id", "away_team_id"}
    if any(k in payload for k in privileged_keys) and not ctx.is_admin:
        for k in list(privileged_keys):
            payload.pop(k, None)
    # audit log: 変更前の値と変更後の値を記録 (match データ改竄の forensic 用)
    from backend.utils.access_log import log_access as _log
    _log(db, "match_updated", user_id=ctx.user_id,
         resource_type="match", resource_id=match_id,
         details={"actor_role": ctx.role, "fields": list(payload.keys())})
    # Phase B 監査: チーム境界に関わる変更は専用イベントを別途残す
    for k in ("owner_team_id", "is_public_pool", "home_team_id", "away_team_id"):
        if k in payload and getattr(match, k, None) != payload[k]:
            _log(
                db,
                f"match_{k}_changed",
                user_id=ctx.user_id,
                resource_type="match",
                resource_id=match_id,
                details={
                    "actor_role": ctx.role,
                    "from": getattr(match, k, None),
                    "to": payload[k],
                },
            )
    # 更新前の関与選手を退避（選手差し替えの場合、旧選手のキャッシュも無効化が必要）
    pre_players = [match.player_a_id, match.player_b_id, match.partner_a_id, match.partner_b_id]
    from backend.utils.db_update import apply_update
    apply_update(match, payload)
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
    if not match or not user_can_access_match(ctx, match):
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    # Phase B-5/B-6: 公開プール / 他チーム所有試合の削除は admin のみ
    if not ctx.is_admin:
        if bool(getattr(match, "is_public_pool", False)):
            raise HTTPException(status_code=403, detail="公開プール試合の削除は admin のみ可能です")
        if match.owner_team_id is not None and match.owner_team_id != ctx.team_id:
            raise HTTPException(status_code=404, detail="試合が見つかりません")
    # analyst は自チームの試合のみ削除可 (cross-team 改竄防止)。admin は全試合可。
    if ctx.is_analyst:
        team = (ctx.team_name or "").strip()
        if not team:
            from backend.utils.control_plane import allow_legacy_header_auth
            if not allow_legacy_header_auth(request):
                raise HTTPException(status_code=403, detail="team_name 未設定")
            # loopback dev/test では admin 同等
        else:
            from backend.db.models import Player as _P
            pids = [p for p in (match.player_a_id, match.player_b_id, match.partner_a_id, match.partner_b_id) if p]
            players = db.query(_P).filter(_P.id.in_(pids)).all() if pids else []
            if not any((p.team or "").strip() == team for p in players):
                raise HTTPException(status_code=403, detail="この試合はあなたのチームではありません")
    # audit log: 削除は forensic 上特に重要
    from backend.utils.access_log import log_access as _log
    _log(db, "match_deleted", user_id=ctx.user_id,
         resource_type="match", resource_id=match_id,
         details={"actor_role": ctx.role})
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
    owner_id, is_public = resolve_owner_team_for_match_create(ctx)
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
        owner_team_id=owner_id,
        is_public_pool=is_public,
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
def get_match_rallies(match_id: int, request: Request, db: Session = Depends(get_db)):
    """試合のラリー一覧 (BOLA/IDOR: ロール別スコープ検証 + Phase B-6)"""
    ctx = get_auth(request)
    match = db.get(Match, match_id)
    if not match or not user_can_access_match(ctx, match):
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    from backend.utils.auth import require_match_scope
    require_match_scope(request, match, db)
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
    model_config = {"extra": "forbid"}
    quality: str = "720"            # "360" / "480" / "720" / "1080" / "best"
    # Electron 限定互換フィールド。Web からは使用不可（下で 403）。
    cookie_browser: str = ""
    # cookies.txt 本文（ユーザが UI からアップロード）。
    # HTTPS + Cloudflare Tunnel 経由のため傍受されない前提。
    # ジョブ完了 or タイムアウト 10 分でサーバ上から即削除する。
    cookies_txt: Optional[str] = None


# 同時 DL 並列数 (800Mbps 想定: 3 並列 × 260Mbps/job)
_DL_SEMAPHORE_SIZE = 3
import asyncio as _asyncio_dl
_dl_semaphore: Optional[_asyncio_dl.Semaphore] = None

def _get_dl_semaphore() -> _asyncio_dl.Semaphore:
    global _dl_semaphore
    if _dl_semaphore is None:
        _dl_semaphore = _asyncio_dl.Semaphore(_DL_SEMAPHORE_SIZE)
    return _dl_semaphore


async def _run_download_with_cookie(
    url: str, job_id: str, quality: str, cookies_file_path: str,
):
    """cookies.txt を使って DL し、完了/失敗問わず cookies.txt を即削除する。"""
    import os as _os
    try:
        async with _get_dl_semaphore():
            await video_downloader.start_download(
                url=url, job_id=job_id, quality=quality,
                cookie_browser="", cookies_file=cookies_file_path,
            )
    finally:
        try:
            if cookies_file_path and _os.path.isfile(cookies_file_path):
                _os.remove(cookies_file_path)
        except Exception:
            pass


@router.post("/matches/{match_id}/download")
async def start_download(
    match_id: int,
    body: DownloadRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    """配信動画ダウンロード開始（yt-dlp + 任意の cookies.txt）。

    - player/coach/analyst/admin 全員が実行可能
    - cookies.txt は一時ファイル保存 + ジョブ完了時に即削除 + chmod 600
    - `cookie_browser` (サーバ側ブラウザ cookie 代理使用) は Web リクエストでは禁止
      (kiyus さんの Chrome cookie を第三者が代理使用する経路を遮断)
    """
    ctx = get_auth(request)
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    if not match.video_url:
        raise HTTPException(status_code=400, detail="動画URLが設定されていません")
    from backend.utils.safe_path import validate_external_url
    validated_url = validate_external_url(match.video_url, field_name="video_url")

    # cookie_browser (サーバ側 chrome cookie 代理) は Electron のローカルリクエスト限定
    # Cloudflare 経由 (CF-Connecting-IP が attacker IP) の場合は 403 で拒否
    if body.cookie_browser:
        from backend.utils.control_plane import is_loopback_request
        if not is_loopback_request(request):
            raise HTTPException(
                status_code=403,
                detail="cookie_browser はローカル実行時 (Electron) のみ利用可能です。Web ブラウザからは cookies_txt を指定してください。",
            )

    # cookies_txt アップロード処理
    cookies_file_path = ""
    if body.cookies_txt:
        cookies_content = body.cookies_txt
        if len(cookies_content) > 1024 * 1024:  # 1MB 上限
            raise HTTPException(status_code=413, detail="cookies.txt が大きすぎます (max 1MB)")
        # null byte を含む cookies.txt は拒否 (ファイル system / yt-dlp パーサ攻撃経路)
        if "\x00" in cookies_content:
            raise HTTPException(status_code=422, detail="cookies.txt に null byte が含まれています")
        # 制御文字 (タブ/改行以外) を拒否
        import re as _re_cc
        if _re_cc.search(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", cookies_content):
            raise HTTPException(status_code=422, detail="cookies.txt に不正な制御文字が含まれています")
        # 先頭行のサニティチェック: yt-dlp の Netscape HTTP Cookie File 形式か
        first_line = cookies_content.splitlines()[0].strip() if cookies_content.strip() else ""
        if not (first_line.startswith("#") or first_line.startswith("# Netscape HTTP Cookie")
                or "\t" in cookies_content[:500]):
            raise HTTPException(
                status_code=422,
                detail="cookies.txt は Netscape HTTP Cookie File 形式である必要があります",
            )
        # 一時ファイルに保存 (ジョブ完了で即削除、chmod 600)
        import os as _os, tempfile as _tf, stat as _stat
        cookies_dir = _os.path.join(_tf.gettempdir(), "ss_cookies")
        try:
            _os.makedirs(cookies_dir, mode=0o700, exist_ok=True)
        except Exception:
            pass
        job_id_tmp = uuid.uuid4().hex
        cookies_file_path = _os.path.join(cookies_dir, f"{job_id_tmp}.txt")
        with open(cookies_file_path, "w", encoding="utf-8") as _f:
            _f.write(cookies_content)
        try:
            _os.chmod(cookies_file_path, _stat.S_IRUSR | _stat.S_IWUSR)  # 0o600
        except Exception:
            pass

    job_id = video_downloader.create_job_id()
    # audit log: DL 開始 (actor_role + cookies_txt 使用フラグ + host)
    from backend.utils.access_log import log_access as _log
    from urllib.parse import urlparse as _up
    _host = _up(validated_url).hostname or ""
    _log(db, "video_dl_started", user_id=ctx.user_id,
         resource_type="match", resource_id=match_id,
         details={
             "actor_role": ctx.role,
             "host": _host,
             "cookies_used": bool(cookies_file_path),
             "quality": body.quality,
         })

    if cookies_file_path:
        background_tasks.add_task(
            _run_download_with_cookie,
            validated_url, job_id, body.quality, cookies_file_path,
        )
    else:
        # cookies 不要 DL も semaphore で並列数制限
        async def _run_no_cookie():
            async with _get_dl_semaphore():
                await video_downloader.start_download(
                    url=validated_url, job_id=job_id, quality=body.quality,
                    cookie_browser=body.cookie_browser,
                )
        background_tasks.add_task(_run_no_cookie)
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
