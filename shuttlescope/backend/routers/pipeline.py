"""INFRA Phase B: 解析パイプライン REST API。

- POST /v1/pipeline/run       : AnalysisJob を enqueue（analyst / coach のみ）
- GET  /v1/pipeline/jobs      : ジョブ一覧（認証済みなら誰でも。権限が無ければ空配列を返す）
- GET  /v1/pipeline/jobs/{id} : 単一ジョブ（同上。権限が無い場合は 404 で秘匿）

権限が無い閲覧者に対して GET を 403 にすると、試合一覧の各行から
1 リクエストずつ 403 がブラウザコンソールに大量出力されてしまう。
閲覧権限管理は「見せないように空で返す」方針とし、書き込み系のみ 403 を維持する。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
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
    # job_type 等のフィールドを任意指定させない + extra フィールド禁止
    # worker 側の未知 job_type 実行による RCE/DoS 経路を遮断する
    model_config = {"extra": "forbid"}
    # match_id は 32bit 正整数に制限 (2**63 等の overflow による 500 回避)
    match_id: int = Field(..., ge=1, le=2**31 - 1)
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

# 許容する job_type 列挙 (worker 側で解釈可能なもののみ)
_ALLOWED_JOB_TYPES = {"full_pipeline"}

# Per-user pipeline run rate limit (CPU/GPU DoS 対策)
# 1 ユーザあたり 10 分に最大 5 job 投入。analyst/coach の業務では十分。
import threading as _th_pipe
import time as _t_pipe
_pipeline_run_counters: dict[int, list[float]] = {}
_pipeline_run_lock = _th_pipe.Lock()
_PIPELINE_WINDOW_SEC = 600
_PIPELINE_MAX_JOBS_PER_WINDOW = 5


@router.post("/run", response_model=JobOut)
def run_pipeline_endpoint(
    body: RunRequest,
    db: Session = Depends(get_db),
    _ctx: AuthCtx = Depends(_require_analyst_or_coach),
):
    """指定試合の解析パイプラインを enqueue する。"""
    # job_type enum 検証 (mass assignment 防御)
    if body.job_type not in _ALLOWED_JOB_TYPES:
        raise HTTPException(status_code=422, detail=f"invalid job_type: {body.job_type!r}")
    # Per-user rate limit (DoS 防御)
    if _ctx.user_id:
        now = _t_pipe.time()
        with _pipeline_run_lock:
            ts_list = _pipeline_run_counters.setdefault(_ctx.user_id, [])
            # 窓外を除去
            cutoff = now - _PIPELINE_WINDOW_SEC
            ts_list[:] = [t for t in ts_list if t >= cutoff]
            if len(ts_list) >= _PIPELINE_MAX_JOBS_PER_WINDOW:
                raise HTTPException(
                    status_code=429,
                    detail=f"パイプライン実行は {_PIPELINE_WINDOW_SEC // 60} 分に {_PIPELINE_MAX_JOBS_PER_WINDOW} 件までです",
                )
            ts_list.append(now)
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
    ctx: AuthCtx = Depends(get_auth),
):
    # 権限が無い閲覧者には空配列を返す（試合一覧バッジ等、全行で叩く用途のため 403 を大量発生させない）
    if ctx.role not in ALLOWED_ROLES:
        return []
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
    ctx: AuthCtx = Depends(get_auth),
):
    # 権限が無い閲覧者にはジョブの存在自体を秘匿するため 404 を返す
    if ctx.role not in ALLOWED_ROLES:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    j = db.get(AnalysisJob, job_id)
    if j is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    # coach は自チーム match のジョブのみ閲覧可能 (BOLA/IDOR 防御)
    if ctx.role == "coach":
        match = db.get(Match, j.match_id)
        if match is not None:
            from backend.utils.auth import require_match_scope
            try:
                require_match_scope(None, match, db) if False else None  # noqa
                # 実コールは下で
            except Exception:
                pass
        # coach の場合は match 経由でスコープチェック
        from backend.db.models import Player as _P
        if match is not None:
            team = (ctx.team_name or "").strip()
            pids = {match.player_a_id, match.player_b_id, match.partner_a_id, match.partner_b_id}
            pids.discard(None)
            if team and pids:
                players = db.query(_P).filter(_P.id.in_(pids)).all()
                if not any((p.team or "").strip() == team for p in players):
                    raise HTTPException(status_code=404, detail="ジョブが見つかりません")
            else:
                raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return _to_out(j)
