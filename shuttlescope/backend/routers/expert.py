"""Expert Labeler Phase 1 API（コーチ・アナリスト向け専門家アノテーション）。

エンドポイント:
    GET  /api/v1/expert/videos           試合一覧（ミス件数・クリップ準備済み件数）
    GET  /api/v1/expert/clips            指定試合のミスストローク一覧
    POST /api/v1/expert/labels           ラベル UPSERT
    GET  /api/v1/expert/labels           既存ラベル取得
    GET  /api/v1/expert/progress         自分の進捗
    GET  /api/v1/expert/export           CSV / JSON エクスポート

ロール制約: analyst または coach のみアクセス可。
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import (
    ClipCache,
    ExpertLabel,
    GameSet,
    Match,
    Player,
    Rally,
    Stroke,
    ShotTypeAnnotation,
)
from backend.services.clip_generator import (
    DEFAULT_FPS,
    compute_frame_index,
    iter_miss_strokes,
)
from backend.utils.auth import AuthCtx, get_auth

router = APIRouter(prefix="/v1/expert", tags=["expert-labeler"])


# ─── ロールガード ───────────────────────────────────────────────────────────

ALLOWED_ROLES = {"analyst", "coach", "admin"}


def require_labeler_role(request: Request) -> AuthCtx:
    """analyst / coach / admin のみ許可する依存性。"""
    ctx = get_auth(request)
    if ctx.role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=403,
            detail="この操作は analyst または coach ロールでのみ実行できます",
        )
    return ctx


def require_admin_role(request: Request) -> AuthCtx:
    """admin のみ許可する依存性。"""
    ctx = get_auth(request)
    if not ctx.is_admin:
        raise HTTPException(
            status_code=403,
            detail="この操作は admin ロールでのみ実行できます",
        )
    return ctx


# ─── スキーマ ───────────────────────────────────────────────────────────────

VALID_POSTURE = {"none", "minor", "major"}
VALID_WEIGHT = {"left", "right", "center", "floating"}
VALID_TIMING = {"early", "optimal", "late"}


class LabelPayload(BaseModel):
    match_id: int = Field(..., ge=1, le=2_147_483_647)
    stroke_id: int = Field(..., ge=1, le=2_147_483_647)
    annotator_role: Literal["coach", "analyst"]
    posture_collapse: str
    weight_distribution: str
    shot_timing: str
    confidence: int = Field(default=2, ge=1, le=3)
    comment: str = ""


class VideoSummary(BaseModel):
    match_id: int
    title: str
    miss_count: int
    clip_ready_count: int
    labeled_count: int


class ClipInfo(BaseModel):
    stroke_id: int
    rally_id: int
    timestamp_sec: Optional[float]
    frame_index: int
    clip_url: Optional[str]
    rally_context: dict
    # INFRA Phase B: ミスストロークのソース種別
    # "manual" = iter_miss_strokes 由来、"auto" = 自動検出器由来、両方なら "manual+auto"
    source: str = "manual"


class LabelOut(BaseModel):
    id: int
    match_id: int
    stroke_id: int
    annotator_role: str
    posture_collapse: str
    weight_distribution: str
    shot_timing: str
    confidence: int
    comment: Optional[str]
    updated_at: datetime

    class Config:
        from_attributes = True


# ─── ヘルパー ───────────────────────────────────────────────────────────────

def _match_title(db: Session, m: Match) -> str:
    """試合表示名（日付 vs 相手名）を構築。"""
    a = db.get(Player, m.player_a_id)
    b = db.get(Player, m.player_b_id)
    a_name = a.name if a else "?"
    b_name = b.name if b else "?"
    return f"{m.date.isoformat()} {a_name} vs {b_name}"


def _fps_for_match(m: Match) -> int:
    fps = getattr(m, "source_fps", None)
    try:
        if fps and int(fps) > 0:
            return int(fps)
    except (TypeError, ValueError):
        pass
    return DEFAULT_FPS


# ─── エンドポイント ─────────────────────────────────────────────────────────

@router.get("/videos", response_model=list[VideoSummary])
def list_videos(
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    """アノテーション対象試合一覧（ミスプロキシ件数 + クリップ準備済み件数）。"""
    # 権限外の閲覧者には空配列を返す（UI が隠れる前に一瞬呼ばれるケースで 403 を出さない）
    if ctx.role not in ALLOWED_ROLES:
        return []
    matches = db.query(Match).filter(Match.deleted_at.is_(None)).all()
    out: list[VideoSummary] = []
    for m in matches:
        miss_rows = iter_miss_strokes(db, m.id)
        miss_count = len(miss_rows)
        clip_ready = (
            db.query(func.count(ClipCache.id))
            .filter(ClipCache.match_id == m.id)
            .scalar()
            or 0
        )
        labeled = (
            db.query(func.count(ExpertLabel.id))
            .filter(ExpertLabel.match_id == m.id)
            .scalar()
            or 0
        )
        out.append(VideoSummary(
            match_id=m.id,
            title=_match_title(db, m),
            miss_count=miss_count,
            clip_ready_count=int(clip_ready),
            labeled_count=int(labeled),
        ))
    return out


@router.get("/clips", response_model=list[ClipInfo])
def list_clips(
    match_id: int = Query(..., ge=1, le=2_147_483_647),
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(require_labeler_role),
):
    """ミスストローク一覧（クリップ URL 付き）。"""
    m = db.get(Match, match_id)
    if not m:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    fps = _fps_for_match(m)
    miss_rows = iter_miss_strokes(db, match_id)

    cache_map = {
        c.stroke_id: c
        for c in db.query(ClipCache).filter(ClipCache.match_id == match_id).all()
    }
    # INFRA Phase B: 自動ミス検出器の結果を合流させ source を付与する
    auto_stroke_ids: set[int] = set()
    try:
        from backend.cv.miss_detector import iter_auto_miss_candidates
        auto_stroke_ids = {c["stroke_id"] for c in iter_auto_miss_candidates(db, match_id)}
    except Exception:
        auto_stroke_ids = set()

    out: list[ClipInfo] = []
    manual_stroke_ids: set[int] = set()
    for rally, stroke in miss_rows:
        manual_stroke_ids.add(stroke.id)
        cache = cache_map.get(stroke.id)
        clip_url = f"/api/v1/expert/clip_file?stroke_id={stroke.id}" if cache else None
        is_auto = stroke.id in auto_stroke_ids
        source = "manual+auto" if is_auto else "manual"
        out.append(ClipInfo(
            stroke_id=stroke.id,
            rally_id=rally.id,
            timestamp_sec=stroke.timestamp_sec,
            frame_index=compute_frame_index(stroke.timestamp_sec, fps),
            clip_url=clip_url,
            rally_context={
                "end_type": rally.end_type,
                "rally_length": rally.rally_length,
                "winner": rally.winner,
                "shot_type": stroke.shot_type,
                "player": stroke.player,
            },
            source=source,
        ))
    return out


@router.post("/labels", response_model=LabelOut)
def upsert_label(
    body: LabelPayload,
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(require_labeler_role),
):
    """ExpertLabel UPSERT（UNIQUE(stroke_id, annotator_role)）。"""
    if body.posture_collapse not in VALID_POSTURE:
        raise HTTPException(status_code=422, detail="posture_collapse invalid")
    if body.weight_distribution not in VALID_WEIGHT:
        raise HTTPException(status_code=422, detail="weight_distribution invalid")
    if body.shot_timing not in VALID_TIMING:
        raise HTTPException(status_code=422, detail="shot_timing invalid")

    m = db.get(Match, body.match_id)
    if not m:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    # Phase B: チーム境界チェック (4-1)
    from backend.utils.auth import user_can_access_match
    if not user_can_access_match(_ctx, m):
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    if not db.get(Stroke, body.stroke_id):
        raise HTTPException(status_code=404, detail="ストロークが見つかりません")

    existing = (
        db.query(ExpertLabel)
        .filter(
            ExpertLabel.stroke_id == body.stroke_id,
            ExpertLabel.annotator_role == body.annotator_role,
        )
        .one_or_none()
    )
    if existing:
        existing.posture_collapse = body.posture_collapse
        existing.weight_distribution = body.weight_distribution
        existing.shot_timing = body.shot_timing
        existing.confidence = body.confidence
        existing.comment = body.comment
        existing.updated_at = datetime.utcnow()
        # Phase B-12: 旧 NULL から書き込み主体に確定させる
        if existing.team_id is None:
            existing.team_id = _ctx.team_id
        label = existing
    else:
        label = ExpertLabel(
            match_id=body.match_id,
            stroke_id=body.stroke_id,
            annotator_role=body.annotator_role,
            posture_collapse=body.posture_collapse,
            weight_distribution=body.weight_distribution,
            shot_timing=body.shot_timing,
            confidence=body.confidence,
            comment=body.comment,
            team_id=_ctx.team_id,
        )
        db.add(label)
    db.commit()
    db.refresh(label)
    return label


@router.get("/labels", response_model=list[LabelOut])
def list_labels(
    match_id: int = Query(..., ge=1, le=2_147_483_647),
    annotator_role: Optional[Literal["coach", "analyst"]] = Query(None),
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(require_labeler_role),
):
    """指定試合（任意で role 絞り込み）のラベル一覧。"""
    from sqlalchemy import or_ as _or
    q = db.query(ExpertLabel).filter(ExpertLabel.match_id == match_id)
    # Phase B-12: 自チームの書き込み + NULL（互換）のみ。admin は全件
    if not _ctx.is_admin:
        q = q.filter(_or(ExpertLabel.team_id.is_(None), ExpertLabel.team_id == _ctx.team_id))
    if annotator_role:
        q = q.filter(ExpertLabel.annotator_role == annotator_role)
    return q.all()


@router.get("/progress")
def get_progress(
    annotator_role: Literal["coach", "analyst"] = Query(...),
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    """自分（指定ロール）の進捗: 全ミス件数 / ラベル済み件数。"""
    if ctx.role not in ALLOWED_ROLES:
        return {"annotator_role": annotator_role, "total": 0, "labeled": 0, "per_match": []}
    matches = db.query(Match).filter(Match.deleted_at.is_(None)).all()
    total = 0
    per_match: list[dict] = []
    for m in matches:
        miss_rows = iter_miss_strokes(db, m.id)
        miss_count = len(miss_rows)
        total += miss_count
        labeled = (
            db.query(func.count(ExpertLabel.id))
            .filter(
                ExpertLabel.match_id == m.id,
                ExpertLabel.annotator_role == annotator_role,
            )
            .scalar()
            or 0
        )
        per_match.append({
            "match_id": m.id,
            "miss_count": miss_count,
            "labeled_count": int(labeled),
        })
    labeled_total = (
        db.query(func.count(ExpertLabel.id))
        .filter(ExpertLabel.annotator_role == annotator_role)
        .scalar()
        or 0
    )
    return {
        "annotator_role": annotator_role,
        "total": total,
        "labeled": int(labeled_total),
        "per_match": per_match,
    }


@router.get("/export")
def export_labels(
    match_id: int = Query(..., ge=1, le=2_147_483_647),
    fmt: Literal["csv", "json"] = Query("json"),
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(require_labeler_role),
):
    """CSV / JSON エクスポート。"""
    if not db.get(Match, match_id):
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    rows = (
        db.query(ExpertLabel)
        .filter(ExpertLabel.match_id == match_id)
        .order_by(ExpertLabel.stroke_id.asc())
        .all()
    )
    records = [
        {
            "id": r.id,
            "match_id": r.match_id,
            "stroke_id": r.stroke_id,
            "annotator_role": r.annotator_role,
            "posture_collapse": r.posture_collapse,
            "weight_distribution": r.weight_distribution,
            "shot_timing": r.shot_timing,
            "confidence": r.confidence,
            "comment": r.comment or "",
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        }
        for r in rows
    ]
    if fmt == "json":
        return {"match_id": match_id, "labels": records}
    # CSV
    buf = io.StringIO()
    fieldnames = list(records[0].keys()) if records else [
        "id", "match_id", "stroke_id", "annotator_role",
        "posture_collapse", "weight_distribution", "shot_timing",
        "confidence", "comment", "updated_at",
    ]
    # CSV/Formula injection (CWE-1236) 対策: 先頭が =, +, -, @, TAB, CR の文字列値は
    # Excel/Sheets で式として実行されるため、先頭にシングルクォートを付与して無効化する。
    # OWASP "CSV Injection" 推奨パターン。
    safe_records = [{k: _csv_safe(v) for k, v in rec.items()} for rec in records]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for rec in safe_records:
        writer.writerow(rec)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="expert_labels_match{match_id}.csv"'},
    )


# ─── ショット種別アノテーション（admin 専用） ───────────────────────────────────

class ShotAnnotationPayload(BaseModel):
    match_id: int = Field(..., ge=1, le=2_147_483_647)
    stroke_id: int = Field(..., ge=1, le=2_147_483_647)
    shot_type: str = Field(..., min_length=1, max_length=64)
    confidence: int = Field(default=2, ge=1, le=3)
    comment: str = Field(default="", max_length=2000)


class ShotAnnotationOut(BaseModel):
    id: int
    match_id: int
    stroke_id: int
    shot_type: str
    confidence: int
    comment: Optional[str]
    annotator_user_id: Optional[int]
    updated_at: datetime

    class Config:
        from_attributes = True


@router.post("/shot_labels", response_model=ShotAnnotationOut)
def upsert_shot_label(
    body: ShotAnnotationPayload,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(require_admin_role),
):
    """ショット種別アノテーション UPSERT（admin のみ）。

    shot_type は canonical 形式に変換して保存する。
    stroke_id ごとに1件。上書き可能。
    """
    from backend.analysis.shot_taxonomy import CANONICAL_SHOTS, canonicalize
    canonical = canonicalize(body.shot_type)
    if canonical not in CANONICAL_SHOTS:
        raise HTTPException(status_code=422, detail=f"shot_type '{body.shot_type}' は認識できません")

    m = db.get(Match, body.match_id)
    if not m:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    if not db.get(Stroke, body.stroke_id):
        raise HTTPException(status_code=404, detail="ストロークが見つかりません")

    existing = (
        db.query(ShotTypeAnnotation)
        .filter(ShotTypeAnnotation.stroke_id == body.stroke_id)
        .one_or_none()
    )
    if existing:
        existing.shot_type = canonical
        existing.confidence = body.confidence
        existing.comment = body.comment
        existing.annotator_user_id = ctx.user_id
        existing.updated_at = datetime.utcnow()
        row = existing
    else:
        row = ShotTypeAnnotation(
            match_id=body.match_id,
            stroke_id=body.stroke_id,
            shot_type=canonical,
            confidence=body.confidence,
            comment=body.comment,
            annotator_user_id=ctx.user_id,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/shot_labels", response_model=list[ShotAnnotationOut])
def list_shot_labels(
    match_id: int = Query(..., ge=1, le=2_147_483_647),
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(require_admin_role),
):
    """指定試合のショット種別アノテーション一覧（admin のみ）。"""
    return (
        db.query(ShotTypeAnnotation)
        .filter(ShotTypeAnnotation.match_id == match_id)
        .order_by(ShotTypeAnnotation.stroke_id.asc())
        .all()
    )


@router.get("/shot_labels/export")
def export_shot_labels(
    match_id: int = Query(..., ge=1, le=2_147_483_647),
    fmt: Literal["csv", "json"] = Query("json"),
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(require_admin_role),
):
    """ショット種別アノテーション CSV / JSON エクスポート（admin のみ）。"""
    if not db.get(Match, match_id):
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    rows = (
        db.query(ShotTypeAnnotation)
        .filter(ShotTypeAnnotation.match_id == match_id)
        .order_by(ShotTypeAnnotation.stroke_id.asc())
        .all()
    )
    records = [
        {
            "id": r.id,
            "match_id": r.match_id,
            "stroke_id": r.stroke_id,
            "shot_type": r.shot_type,
            "confidence": r.confidence,
            "comment": r.comment or "",
            "annotator_user_id": r.annotator_user_id,
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        }
        for r in rows
    ]
    if fmt == "json":
        return {"match_id": match_id, "shot_labels": records}
    buf = io.StringIO()
    fieldnames = list(records[0].keys()) if records else [
        "id", "match_id", "stroke_id", "shot_type", "confidence", "comment",
        "annotator_user_id", "updated_at",
    ]
    safe_records = [{k: _csv_safe(v) for k, v in rec.items()} for rec in records]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for rec in safe_records:
        writer.writerow(rec)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="shot_labels_match{match_id}.csv"'},
    )


_CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value):
    """CSV/Formula injection 対策: Excel/Sheets が式として解釈する先頭文字を無効化する。

    str 以外（int/float/None など）はそのまま返す。
    str 値の先頭が =, +, -, @, TAB, CR のいずれかなら ' を前置する。
    """
    if not isinstance(value, str) or not value:
        return value
    if value[0] in _CSV_DANGEROUS_PREFIXES:
        return "'" + value
    return value
