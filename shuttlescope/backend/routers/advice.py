"""アドバイス API: 6 context をひとつの endpoint で扱う。

設計指針:
  - 各 context handler はサービス層 (backend.services.advice) に委譲。
  - 返却は常に `{success, advice: AdviceCard|null, status, reason?, period?}`。
  - advice が null の場合 frontend は「計測中」「データ不足」を素直に出す。
  - 「それっぽい」生成は一切やらない (信頼性最優先)。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.utils.auth import AuthCtx, check_export_player_scope, get_auth
from backend.services.advice import (
    advice_condition_header,
    advice_dashboard_overview,
    advice_growth_timeline,
    advice_player_home,
    advice_post_match_save,
    advice_prediction_tab,
)


router = APIRouter(tags=["advice"])


_VALID_CONTEXTS = {
    "dashboard.overview",
    "post_match_save",
    "condition.header",
    "prediction.tab",
    "growth.timeline",
    "player.home",
}


@router.get("/advice")
def get_advice(
    context: str,
    request: Request,
    db: Session = Depends(get_db),
    player_id: Optional[int] = Query(None, ge=1),
    match_id: Optional[int] = Query(None, ge=1),
    opponent_id: Optional[int] = Query(None, ge=1),
):
    """指定 context の advice を返す。"""
    if context not in _VALID_CONTEXTS:
        raise HTTPException(status_code=400, detail=f"unknown context: {context}")
    ctx = get_auth(request)
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="auth required")

    # player ロールは自分の player_id しか見られない
    if ctx.role == "player":
        if not ctx.player_id:
            raise HTTPException(status_code=403, detail="player role missing player_id")
        # player_id が渡されていなければ自分。違う player_id は禁止。
        if player_id is None:
            player_id = ctx.player_id
        elif player_id != ctx.player_id:
            raise HTTPException(status_code=403, detail="player cannot view other player advice")
    else:
        # coach / analyst / admin
        # post_match_save に限り、match_id から player を推定可能 (annotator など)
        if not player_id and context == "post_match_save" and match_id:
            from backend.db.models import Match
            mrec = db.get(Match, match_id)
            if mrec:
                # annotator が player と紐付くケースを優先
                if mrec.annotator_id and ctx.player_id == mrec.annotator_id:
                    player_id = ctx.player_id
                else:
                    # 安全側: player_a を採用 (アナリスト向け運用、後で UI で切替可)
                    player_id = mrec.player_a_id
        if not player_id:
            raise HTTPException(status_code=400, detail="player_id required")
        check_export_player_scope(ctx, player_id, db)

    if context == "dashboard.overview":
        return advice_dashboard_overview(db, player_id, ctx)
    if context == "post_match_save":
        if not match_id:
            raise HTTPException(status_code=400, detail="match_id required for post_match_save")
        return advice_post_match_save(db, player_id, match_id, ctx)
    if context == "condition.header":
        return advice_condition_header(db, player_id, ctx)
    if context == "prediction.tab":
        return advice_prediction_tab(db, player_id, opponent_id, ctx)
    if context == "growth.timeline":
        return advice_growth_timeline(db, player_id, ctx)
    if context == "player.home":
        return advice_player_home(db, player_id, ctx)

    raise HTTPException(status_code=400, detail="unhandled context")
