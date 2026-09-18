"""Compact player summary endpoint (Slice Y).

GET /api/insights/player_summary?player_id=&date_from=&date_to=&sections=

player ロールは outcomes.win_rate の生値を受け取らず、bucketed な
growth_phase ("early"/"developing"/"established") に差し替える。
coach/analyst/admin は raw payload を受け取る。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.analysis.insights.player_summary_service import build_player_summary
from backend.db.database import get_db
from backend.utils.auth import AuthCtx, get_auth

router = APIRouter()


def _growth_phase_from_sample(matches: int) -> str:
    if matches < 5:
        return "early"
    if matches < 20:
        return "developing"
    return "established"


def _redact_for_player(payload: dict) -> dict:
    """player ロール向けに outcomes.win_rate を bucketed に置き換える."""
    if "outcomes" not in payload and "sample" not in payload:
        return payload
    sample = payload.get("sample") or {}
    n_matches = int(sample.get("matches", 0)) if isinstance(sample, dict) else 0
    if "outcomes" in payload and isinstance(payload["outcomes"], dict):
        outcomes = dict(payload["outcomes"])
        outcomes.pop("win_rate", None)
        outcomes.pop("set_win_rate", None)
        outcomes["growth_phase"] = _growth_phase_from_sample(n_matches)
        payload = dict(payload)
        payload["outcomes"] = outcomes
    return payload


@router.get("/insights/player_summary")
def get_player_summary(
    player_id: int = Query(..., ge=1),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sections: Optional[str] = Query(
        None,
        description="comma-separated allowlist: identity,sample,outcomes,shot_mix,zones,conditions,recent_trend",
    ),
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
) -> dict:
    section_list: Optional[list[str]] = None
    if sections is not None:
        section_list = [s.strip() for s in sections.split(",") if s.strip()]

    # このエンドポイントには認可が一切無く、`player_id` を変えるだけで
    # **誰でも全選手**の識別情報・成績・ショット構成・ゾーン分布・体調データを
    # 引けていた (教科書的な IDOR)。しかも `/api/insights/` は
    # main.py のスコープ強制 middleware の prefix リストに入っていないので、
    # 第二の防御線も無い。ここで閉じる。
    from backend.utils.auth import can_access_player

    if ctx.is_player:
        # 選手は自分のサマリのみ。他選手の player_id を指定させない。
        if not ctx.player_id or player_id != ctx.player_id:
            raise HTTPException(status_code=404, detail="選手が見つかりません")
    elif not can_access_player(ctx, player_id, db):
        raise HTTPException(status_code=404, detail="選手が見つかりません")

    payload = build_player_summary(
        db, player_id, date_from, date_to, section_list
    )
    if ctx.role in ("player", "demo"):
        # demo も実データを見せない対象。player と同じ伏せ方をする。
        payload = _redact_for_player(payload)
    return payload
