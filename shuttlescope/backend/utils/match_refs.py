"""body / query で渡された set_id / rally_id / stroke_id が、指定の試合に属するか検証する。

comments / bookmarks は match_id で team scope を検査するが、同じ本文の rally_id などが
別チームの試合の行を指していても保存できてしまうため、ここで整合を強制する。
存在しない場合と他の試合の行の場合は区別せず同じ 422 を返す (他チームの id の存在を漏らさない)。
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.db.models import GameSet, Rally, Stroke


def require_refs_in_match(
    db: Session,
    match_id: int,
    *,
    set_id: Optional[int] = None,
    rally_id: Optional[int] = None,
    stroke_id: Optional[int] = None,
) -> None:
    """set_id / rally_id / stroke_id が match_id の試合に属し、互いに矛盾しないことを検証する。"""
    bad = HTTPException(status_code=422, detail="set_id / rally_id / stroke_id が試合と一致しません")
    set_row = None
    rally_row = None
    if set_id is not None:
        set_row = db.get(GameSet, set_id)
        if set_row is None or set_row.match_id != match_id:
            raise bad
    if rally_id is not None:
        rally_row = db.get(Rally, rally_id)
        if rally_row is None:
            raise bad
        if set_row is not None and rally_row.set_id != set_row.id:
            raise bad
        parent = set_row if set_row is not None else db.get(GameSet, rally_row.set_id)
        if parent is None or parent.match_id != match_id:
            raise bad
    if stroke_id is not None:
        stroke_row = db.get(Stroke, stroke_id)
        if stroke_row is None:
            raise bad
        if rally_row is not None:
            if stroke_row.rally_id != rally_row.id:
                raise bad
            return
        rally_of_stroke = db.get(Rally, stroke_row.rally_id)
        if rally_of_stroke is None:
            raise bad
        if set_row is not None and rally_of_stroke.set_id != set_row.id:
            raise bad
        parent = set_row if set_row is not None else db.get(GameSet, rally_of_stroke.set_id)
        if parent is None or parent.match_id != match_id:
            raise bad
