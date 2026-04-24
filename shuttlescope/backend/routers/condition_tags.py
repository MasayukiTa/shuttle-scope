"""コンディション期間タグ API (/api/condition_tags)。

選手ごとに任意の期間ラベル（合宿 / 大会前 / ストレス期など）を登録し、
期間内外でコンディション指標の差分比較に利用する。
"""
from __future__ import annotations

import re
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import ConditionTag, Player

router = APIRouter(prefix="/api/condition_tags", tags=["condition_tags"])


_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ConditionTagCreate(BaseModel):
    player_id: int
    label: str = Field(..., min_length=1, max_length=100)
    start_date: _date
    end_date: Optional[_date] = None
    color: str = Field(default="#3b82f6")

    @field_validator("color")
    @classmethod
    def _check_color(cls, v: str) -> str:
        if not _COLOR_RE.match(v):
            raise ValueError("color must be #RRGGBB")
        return v


class ConditionTagUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=100)
    start_date: Optional[_date] = None
    end_date: Optional[_date] = None
    color: Optional[str] = None

    @field_validator("color")
    @classmethod
    def _check_color(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _COLOR_RE.match(v):
            raise ValueError("color must be #RRGGBB")
        return v


def _serialize(t: ConditionTag) -> dict:
    return {
        "id": t.id,
        "player_id": t.player_id,
        "label": t.label,
        "start_date": t.start_date.isoformat() if t.start_date else None,
        "end_date": t.end_date.isoformat() if t.end_date else None,
        "color": t.color,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("")
def list_condition_tags(
    player_id: int = Query(...),
    db: Session = Depends(get_db),
):
    if not db.get(Player, player_id):
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    rows = (
        db.query(ConditionTag)
        .filter(ConditionTag.player_id == player_id)
        .order_by(ConditionTag.start_date.asc(), ConditionTag.id.asc())
        .all()
    )
    return {"success": True, "data": [_serialize(t) for t in rows]}


@router.post("", status_code=201)
def create_condition_tag(body: ConditionTagCreate, db: Session = Depends(get_db)):
    if not db.get(Player, body.player_id):
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    if body.end_date is not None and body.end_date < body.start_date:
        raise HTTPException(status_code=422, detail="end_date は start_date 以降である必要があります")
    tag = ConditionTag(
        player_id=body.player_id,
        label=body.label,
        start_date=body.start_date,
        end_date=body.end_date,
        color=body.color,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return {"success": True, "data": _serialize(tag)}


@router.put("/{tag_id}")
def update_condition_tag(
    tag_id: int, body: ConditionTagUpdate, db: Session = Depends(get_db)
):
    tag = db.get(ConditionTag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="タグが見つかりません")
    data = body.model_dump(exclude_unset=True)
    from backend.utils.db_update import apply_update
    apply_update(tag, data)
    if tag.end_date is not None and tag.end_date < tag.start_date:
        raise HTTPException(status_code=422, detail="end_date は start_date 以降である必要があります")
    db.commit()
    db.refresh(tag)
    return {"success": True, "data": _serialize(tag)}


@router.delete("/{tag_id}")
def delete_condition_tag(tag_id: int, db: Session = Depends(get_db)):
    tag = db.get(ConditionTag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="タグが見つかりません")
    db.delete(tag)
    db.commit()
    return {"success": True, "data": {"id": tag_id}}
