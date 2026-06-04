"""録画/動画スロット API。

設計: 試合枠(match)を先に作成 → match_id 確定 → その match の **枝番(branch_no)** に
複数動画(upload/live)を結びつける。録画/upload の制御面。

- POST /api/matches/{match_id}/recordings : 枝番を自動採番してスロット作成 (privileged)
- GET  /api/matches/{match_id}/recordings : 一覧 (枝番順)
- PATCH /api/recordings/{rec_id}          : 状態/パス/解像度等を更新 (privileged。live 録画完了時など)

動画内部パスは露出させず video_token を返す (Match と同方針)。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, Recording
from backend.utils.auth import get_auth

router = APIRouter()

_PRIVILEGED = {"admin", "analyst", "coach"}
_VALID_KIND = {"upload", "live"}
_VALID_STATUS = {"pending", "recording", "ready", "failed"}


def _require_privileged(request: Request):
    ctx = get_auth(request)
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if ctx.role not in _PRIVILEGED:
        raise HTTPException(status_code=403, detail="privileged role required")
    return ctx


class RecordingCreate(BaseModel):
    kind: str = Field(default="upload", max_length=20)
    source_kind: Optional[str] = Field(default=None, max_length=20)
    label: Optional[str] = Field(default=None, max_length=100)
    resolution: Optional[str] = Field(default=None, max_length=20)
    fps: Optional[int] = Field(default=None, ge=1, le=1000)


class RecordingPatch(BaseModel):
    status: Optional[str] = Field(default=None, max_length=20)
    video_local_path: Optional[str] = Field(default=None, max_length=500)
    resolution: Optional[str] = Field(default=None, max_length=20)
    fps: Optional[int] = Field(default=None, ge=1, le=1000)
    label: Optional[str] = Field(default=None, max_length=100)
    ended: Optional[bool] = None  # True で ended_at を now に


def _to_dict(r: Recording) -> dict:
    # 内部パス(video_local_path)は露出しない。配信は video_token 経由。
    return {
        "id": r.id,
        "match_id": r.match_id,
        "branch_no": r.branch_no,
        "kind": r.kind,
        "source_kind": r.source_kind,
        "status": r.status,
        "video_token": r.video_token,
        "resolution": r.resolution,
        "fps": r.fps,
        "label": r.label,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
    }


@router.post("/matches/{match_id}/recordings", status_code=201)
def create_recording(match_id: int, body: RecordingCreate, request: Request, db: Session = Depends(get_db)):
    _require_privileged(request)
    if body.kind not in _VALID_KIND:
        raise HTTPException(status_code=422, detail=f"invalid kind: {body.kind!r}")
    if not db.get(Match, match_id):
        raise HTTPException(status_code=404, detail="match not found")
    # 枝番を採番 (match 内 max+1, 1 始まり)
    max_branch = (
        db.query(func.max(Recording.branch_no)).filter(Recording.match_id == match_id).scalar()
    )
    branch_no = (max_branch or 0) + 1
    rec = Recording(
        match_id=match_id,
        branch_no=branch_no,
        kind=body.kind,
        source_kind=body.source_kind,
        label=body.label,
        resolution=body.resolution,
        fps=body.fps,
        status="recording" if body.kind == "live" else "pending",
        started_at=datetime.utcnow() if body.kind == "live" else None,
        video_token=str(uuid4()),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _to_dict(rec)


@router.get("/matches/{match_id}/recordings")
def list_recordings(match_id: int, request: Request, db: Session = Depends(get_db)):
    get_auth(request)  # 認証は GlobalAuthMiddleware で担保。ここは存在のみ確認。
    if not db.get(Match, match_id):
        raise HTTPException(status_code=404, detail="match not found")
    rows = (
        db.query(Recording)
        .filter(Recording.match_id == match_id)
        .order_by(Recording.branch_no.asc())
        .all()
    )
    return {"success": True, "data": [_to_dict(r) for r in rows]}


@router.patch("/recordings/{rec_id}")
def patch_recording(rec_id: int, body: RecordingPatch, request: Request, db: Session = Depends(get_db)):
    _require_privileged(request)
    rec = db.get(Recording, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="recording not found")
    if body.status is not None:
        if body.status not in _VALID_STATUS:
            raise HTTPException(status_code=422, detail=f"invalid status: {body.status!r}")
        rec.status = body.status
    if body.video_local_path is not None:
        rec.video_local_path = body.video_local_path
    if body.resolution is not None:
        rec.resolution = body.resolution
    if body.fps is not None:
        rec.fps = body.fps
    if body.label is not None:
        rec.label = body.label
    if body.ended:
        rec.ended_at = datetime.utcnow()
    db.commit()
    db.refresh(rec)
    return _to_dict(rec)
