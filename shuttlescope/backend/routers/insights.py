"""Growth Snapshot insights router.

GET /api/insights/growth_snapshot?player_id=&period_days=30&lang=ja

選手安全な「伸びしろ」プロセを返す。LLM プラガブル (現状 template)。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.analysis.insights import (
    InsightContext,
    get_generator,
)
from backend.utils.auth import get_auth, AuthCtx

router = APIRouter()


def _example_analytics() -> dict:
    """既存ルータと疎結合に保つため、最初は例示データを返す。

    将来: shot_win_loss / recent_form / growth_timeline_delta を内部関数として
    取り込み、本物の数値で置換する。meta.example=true で UI に明示する。
    """
    return {
        "shot_win_loss": [
            {"shot": "smash", "win_rate": 0.62, "delta_pp": 4.0,
             "sample_n": 120, "alt_shot": "drop"},
            {"shot": "clear", "win_rate": 0.55, "delta_pp": 1.5,
             "sample_n": 90, "alt_shot": "drive"},
        ],
        "recent_form": {"win_rate": 0.58, "delta_pp": 6.0, "sample_n": 40},
        "growth_timeline_delta": {
            "metric": "serve_win_rate", "delta_pp": 3.5, "sample_n": 80,
        },
    }


@router.get("/insights/growth_snapshot")
def get_growth_snapshot(
    request: Request,
    player_id: int = Query(..., ge=1, le=2_147_483_647),
    period_days: int = Query(30, ge=1, le=365),
    lang: str = Query("ja", pattern="^(ja|en)$"),
    ctx: AuthCtx = Depends(get_auth),
) -> dict:
    # ── ロール: player 以上。未認証(None)は拒否 ───────────────────
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="auth required")
    if ctx.role not in {"player", "coach", "analyst", "admin", "demo"}:
        raise HTTPException(status_code=403, detail="forbidden")
    # player は本人のみ
    if ctx.role == "player" and ctx.player_id is not None and ctx.player_id != player_id:
        raise HTTPException(status_code=403, detail="player can only view own snapshot")

    analytics = _example_analytics()

    insight_ctx: InsightContext = {
        "player_id": player_id,
        "period_days": period_days,
        "analytics": analytics,
        "role": ctx.role,
        "lang": lang,
    }
    generator = get_generator()
    result = generator.generate(insight_ctx)

    return {
        "items": result["items"],
        "generator": result["generator"],
        "generated_at": result.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        "meta": {
            "example": True,
            "disclaimer": "template-generated; LLM-pluggable",
            "period_days": period_days,
            "lang": lang,
        },
    }
