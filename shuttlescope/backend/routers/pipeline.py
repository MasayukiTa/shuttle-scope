"""INFRA Phase B: 解析パイプライン REST API。

- POST /v1/pipeline/run       : AnalysisJob を enqueue
- GET  /v1/pipeline/jobs      : ジョブ一覧
- GET  /v1/pipeline/jobs/{id} : 単一ジョブ
ロール制約: analyst / coach のみ。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import AnalysisJob, Match
from backend.pipeline.jobs import enqueue
from backend.utils.auth import AuthCtx, get_auth


router = APIRouter(prefix="/v1/pipeline", tags=["pipeline"])

ALLOWED_ROLES = {"analyst", "coach"}


def _require_analyst_or_coach(ctx: AuthCtx = Depends(get_auth)) -> AuthCtx:
    if ctx.role not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="analyst/coach のみアクセス可能")
    return ctx


# ─── スキーマ ────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    match_id: int
    job_type: str = "full_pipeline"


class JobOut(BaseModel):
    id: int
    match_id: int
    job_type: str
    status: str
    progress: float
    error: Optional[str] = None
    enqueued_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    worker_host: Optional[str] = None


def _to_out(j: AnalysisJob) -> JobOut:
    return JobOut(
        id=j.id,
        match_id=j.match_id,
        job_type=j.job_type,
        status=j.status,
        progress=float(j.progress or 0.0),
        error=j.error,
        enqueued_at=j.enqueued_at.isoformat() if j.enqueued_at else None,
        started_at=j.started_at.isoformat() if j.started_at else None,
        finished_at=j.finished_at.isoformat() if j.finished_at else None,
        worker_host=j.worker_host,
    )


# ─── エンドポイント ─────────────────────────────────────────────────────────

@router.post("/run", response_model=JobOut)
def run_pipeline_endpoint(
    body: RunRequest,
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(_require_analyst_or_coach),
):
    """指定試合の解析パイプラインを enqueue する。"""
    if not db.get(Match, body.match_id):
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    job = enqueue(db, body.match_id, job_type=body.job_type)
    return _to_out(job)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    match_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(_require_analyst_or_coach),
):
    q = db.query(AnalysisJob)
    if match_id is not None:
        q = q.filter(AnalysisJob.match_id == match_id)
    if status:
        q = q.filter(AnalysisJob.status == status)
    rows = q.order_by(AnalysisJob.enqueued_at.desc()).limit(limit).all()
    return [_to_out(r) for r in rows]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(_require_analyst_or_coach),
):
    j = db.get(AnalysisJob, job_id)
    if j is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return _to_out(j)
