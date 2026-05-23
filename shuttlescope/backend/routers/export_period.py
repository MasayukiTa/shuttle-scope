"""Slice Z: 期間バルクエクスポート (/api/export/period)

player_id + date_from/date_to で絞った試合群を 1 リクエストで取得する。
format=json (default) は JSON 配列、format=ndjson は streaming NDJSON。
"""
from __future__ import annotations

import json
import logging
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match
from backend.routers.data_package import (
    ALLOWED_SECTIONS,
    _build_match_package,
    _parse_sections,
)
from backend.utils.auth import (
    AuthCtx,
    UserRole,
    check_export_match_scope,
    get_auth,
)

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_MATCHES_PER_PERIOD = 500
_ALLOWED_ROLES = {
    UserRole.ANALYST.value,
    UserRole.COACH.value,
    UserRole.ADMIN.value,
    UserRole.DEMO.value,
}


def _parse_iso_date(value: Optional[str], field: str) -> Optional[_date]:
    if value is None or not str(value).strip():
        return None
    try:
        return _date.fromisoformat(str(value).strip())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{field} は YYYY-MM-DD 形式で指定してください",
        )


def _gate_role(ctx: AuthCtx) -> None:
    """player ロールはバルク期間エクスポートに使えない (Slice Z 仕様)."""
    if ctx.role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=403,
            detail="期間バルクエクスポートには analyst / coach / admin / demo ロールが必要です",
        )


@router.get("/export/period")
def export_period(
    request: Request,
    player_id: int = Query(..., ge=1),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    format: str = Query("json"),
    sections: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    ctx = get_auth(request)
    _gate_role(ctx)

    d_from = _parse_iso_date(date_from, "date_from")
    d_to = _parse_iso_date(date_to, "date_to")

    fmt = (format or "json").strip().lower()
    if fmt not in {"json", "ndjson"}:
        raise HTTPException(status_code=400, detail="format は json か ndjson のみ対応です")

    selected_sections, sections_csv = _parse_sections(sections)

    q = db.query(Match).filter(
        (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
    )
    if d_from is not None:
        q = q.filter(Match.date >= d_from)
    if d_to is not None:
        q = q.filter(Match.date <= d_to)
    q = q.order_by(Match.date.asc().nullslast(), Match.id.asc())

    matches = q.limit(MAX_MATCHES_PER_PERIOD + 1).all()
    if len(matches) > MAX_MATCHES_PER_PERIOD:
        raise HTTPException(
            status_code=413,
            detail=(
                f"期間内の試合が {MAX_MATCHES_PER_PERIOD} 件を超えました。"
                "date_from / date_to を狭めて再試行してください。"
            ),
        )

    # role / team scope を一括チェック（admin 以外は対象が空でも安全側に）
    if matches:
        check_export_match_scope(ctx, matches, db)

    common_headers = {
        "X-Sections-Applied": sections_csv,
        "X-Period-Match-Count": str(len(matches)),
    }
    if d_from or d_to:
        common_headers["X-Date-Range"] = f"{date_from or ''}..{date_to or ''}"

    if fmt == "ndjson":
        def _gen():
            for m in matches:
                pkg = _build_match_package(db, m, selected_sections)
                yield json.dumps(pkg, ensure_ascii=False) + "\n"
        return StreamingResponse(
            _gen(),
            media_type="application/x-ndjson",
            headers=common_headers,
        )

    # JSON 配列
    items = [_build_match_package(db, m, selected_sections) for m in matches]
    body = json.dumps(items, ensure_ascii=False).encode("utf-8")
    return Response(
        content=body,
        media_type="application/json",
        headers=common_headers,
    )
