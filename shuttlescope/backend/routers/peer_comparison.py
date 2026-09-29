"""peer_comparison router — admin 専用 community peer cohort 集計 (research tier)

セーフティガード:
  - router-level Depends(require_admin) で player/coach/analyst を 403。
  - k-anonymity (MIN_COHORT_N) は analysis 層で enforce。
  - demo team は analysis 層で除外。
  - 全リクエストを security_events に audit log として記録。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.utils.auth import require_admin, get_auth
from backend.utils.security_log import emit_security_event
from backend.analysis.peer_comparison import (
    compute_peer_cohort_stats,
    SUPPORTED_METRICS,
    MIN_COHORT_N,
)


logger = logging.getLogger(__name__)


router = APIRouter(dependencies=[Depends(require_admin)])


class _CohortBody(BaseModel):
    age_bucket: Optional[str] = Field(default=None)
    level: Optional[str] = Field(default=None)
    handedness: Optional[str] = Field(default=None)
    gender: Optional[str] = Field(default=None)
    singles_doubles: Optional[str] = Field(default=None)
    metrics: Optional[list[str]] = Field(default=None)


@router.post("/analysis/research/peer_cohort_stats")
def peer_cohort_stats(
    body: _CohortBody,
    request: Request,
    db: Session = Depends(get_db),
):
    """admin-only research-tier peer cohort 集計エンドポイント。"""
    cohort: dict = {}
    for k in ("age_bucket", "level", "handedness", "gender", "singles_doubles"):
        v = getattr(body, k)
        if v:
            cohort[k] = v

    metrics = body.metrics if body.metrics else list(SUPPORTED_METRICS)
    result = compute_peer_cohort_stats(db, cohort, metrics)  # type: ignore[arg-type]

    # audit
    try:
        try:
            ctx = get_auth(request)
            user_id = ctx.user_id
        except Exception:
            user_id = None
        emit_security_event(
            event_type="peer_comparison_query",
            severity="info",
            user_id=user_id,
            path=str(request.url.path),
            method="POST",
            details={
                "cohort": cohort,
                "metrics": metrics,
                "n": int(result.get("n", 0)),
                "available": bool(result.get("available", False)),
            },
        )
    except Exception:
        logger.exception("peer_comparison audit emit failed")

    return {
        "success": True,
        "data": result,
        "meta": {
            "tier": "research",
            "min_cohort_n": MIN_COHORT_N,
            "evidence_level": "experimental",
        },
    }
