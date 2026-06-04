"""サーバ稼働状況 / 予定メンテ / 障害インシデント API。

- GET  /api/public/status            : 公開 (認証不要)。現在状態 + 予定メンテ + 直近インシデント
- POST /api/status/incidents         : インシデント作成 (admin)
- PATCH /api/status/incidents/{id}   : 更新/解決 (admin)
- POST /api/status/maintenance       : メンテ告知作成 (admin)
- PATCH /api/status/maintenance/{id} : 更新 (admin)
- POST /api/status/announcements      : 更新情報/お知らせ作成 (admin)
- PATCH /api/status/announcements/{id}: 更新 (admin)

「死活の時刻」= began_at/resolved_at、「理由」= reason に運用者が記す (自動判定しない)。
更新情報(announcements)は運用者がキュレーションした公開可の項目のみ掲載する
(内部 dev CHANGELOG は security/CV 詳細を含むため公開しない)。
公開ページ(Jinja)/トップバナーはこの API を読む。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Announcement, MaintenanceWindow, StatusIncident
from backend.utils.auth import get_auth

router = APIRouter()

_SEVERITY = {"minor", "major", "critical"}
_INC_STATUS = {"investigating", "identified", "monitoring", "resolved"}
_MNT_STATUS = {"scheduled", "in_progress", "completed", "canceled"}
_ANN_STATUS = {"published", "draft"}


def _require_admin(request: Request):
    ctx = get_auth(request)
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    return ctx


def _inc_dict(i: StatusIncident) -> dict:
    return {
        "id": i.id, "title": i.title, "reason": i.reason, "severity": i.severity,
        "component": i.component, "status": i.status,
        "began_at": i.began_at.isoformat() if i.began_at else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
    }


def _mnt_dict(m: MaintenanceWindow) -> dict:
    return {
        "id": m.id, "title": m.title, "body": m.body, "status": m.status,
        "scheduled_start": m.scheduled_start.isoformat() if m.scheduled_start else None,
        "scheduled_end": m.scheduled_end.isoformat() if m.scheduled_end else None,
    }


def _ann_dict(a: Announcement) -> dict:
    return {
        "id": a.id, "title": a.title, "body": a.body, "status": a.status,
        "pinned": bool(a.pinned),
        "published_at": a.published_at.isoformat() if a.published_at else None,
    }


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    reason: Optional[str] = None
    severity: str = Field(default="minor", max_length=20)
    component: Optional[str] = Field(default=None, max_length=50)
    began_at: Optional[datetime] = None


class IncidentPatch(BaseModel):
    status: Optional[str] = Field(default=None, max_length=20)
    reason: Optional[str] = None
    resolved: Optional[bool] = None


class MaintenanceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: Optional[str] = None
    scheduled_start: datetime
    scheduled_end: Optional[datetime] = None


class MaintenancePatch(BaseModel):
    status: Optional[str] = Field(default=None, max_length=20)
    body: Optional[str] = None
    scheduled_end: Optional[datetime] = None


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: Optional[str] = None
    pinned: bool = False
    published_at: Optional[datetime] = None


class AnnouncementPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    body: Optional[str] = None
    status: Optional[str] = Field(default=None, max_length=20)
    pinned: Optional[bool] = None


def compute_public_status(db: Session) -> dict:
    """公開ステータスの集計ロジック (API と Jinja `/status` ページで共有)。

    - overall: 未解決 incident の severity から算出 (critical→down / それ以外の未解決→degraded)。
    - active_incidents: 未解決 (status != resolved) を began_at 降順。
    - recent_incidents: 直近 20 件 (解決済み含む、履歴用)。
    - maintenance: scheduled/in_progress かつ終了が未来 (or 未定) のものを開始昇順。
    - announcements: published のみ、pinned 優先 → published_at 降順 (直近 10 件)。
    """
    unresolved = (
        db.query(StatusIncident)
        .filter(StatusIncident.status != "resolved")
        .order_by(StatusIncident.began_at.desc())
        .all()
    )
    if any(i.severity in ("critical", "major") for i in unresolved):
        overall = "down" if any(i.severity == "critical" for i in unresolved) else "degraded"
    elif unresolved:
        overall = "degraded"
    else:
        overall = "operational"
    recent = (
        db.query(StatusIncident).order_by(StatusIncident.began_at.desc()).limit(20).all()
    )
    now = datetime.utcnow()
    maint = (
        db.query(MaintenanceWindow)
        .filter(MaintenanceWindow.status.in_(["scheduled", "in_progress"]),
                ((MaintenanceWindow.scheduled_end == None) | (MaintenanceWindow.scheduled_end >= now)))  # noqa: E711
        .order_by(MaintenanceWindow.scheduled_start.asc())
        .all()
    )
    announcements = (
        db.query(Announcement)
        .filter(Announcement.status == "published")
        .order_by(Announcement.pinned.desc(), Announcement.published_at.desc())
        .limit(10)
        .all()
    )
    return {
        "overall": overall,
        "active_incidents": [_inc_dict(i) for i in unresolved],
        "recent_incidents": [_inc_dict(i) for i in recent],
        "maintenance": [_mnt_dict(m) for m in maint],
        "announcements": [_ann_dict(a) for a in announcements],
        "checked_at": now.isoformat(),
    }


@router.get("/public/status")
def public_status(db: Session = Depends(get_db)):
    """公開ステータス。認証不要 (/api/public/* は anon 許可)。"""
    return compute_public_status(db)


@router.post("/status/incidents", status_code=201)
def create_incident(body: IncidentCreate, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    if body.severity not in _SEVERITY:
        raise HTTPException(status_code=422, detail="invalid severity")
    inc = StatusIncident(
        title=body.title, reason=body.reason, severity=body.severity,
        component=body.component, began_at=body.began_at or datetime.utcnow(),
        status="investigating",
    )
    db.add(inc); db.commit(); db.refresh(inc)
    return _inc_dict(inc)


@router.patch("/status/incidents/{inc_id}")
def patch_incident(inc_id: int, body: IncidentPatch, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    inc = db.get(StatusIncident, inc_id)
    if not inc:
        raise HTTPException(status_code=404, detail="incident not found")
    if body.status is not None:
        if body.status not in _INC_STATUS:
            raise HTTPException(status_code=422, detail="invalid status")
        inc.status = body.status
    if body.reason is not None:
        inc.reason = body.reason
    if body.resolved:
        inc.status = "resolved"
        inc.resolved_at = datetime.utcnow()
    db.commit(); db.refresh(inc)
    return _inc_dict(inc)


@router.post("/status/maintenance", status_code=201)
def create_maintenance(body: MaintenanceCreate, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    m = MaintenanceWindow(
        title=body.title, body=body.body, scheduled_start=body.scheduled_start,
        scheduled_end=body.scheduled_end, status="scheduled",
    )
    db.add(m); db.commit(); db.refresh(m)
    return _mnt_dict(m)


@router.patch("/status/maintenance/{mnt_id}")
def patch_maintenance(mnt_id: int, body: MaintenancePatch, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    m = db.get(MaintenanceWindow, mnt_id)
    if not m:
        raise HTTPException(status_code=404, detail="maintenance not found")
    if body.status is not None:
        if body.status not in _MNT_STATUS:
            raise HTTPException(status_code=422, detail="invalid status")
        m.status = body.status
    if body.body is not None:
        m.body = body.body
    if body.scheduled_end is not None:
        m.scheduled_end = body.scheduled_end
    db.commit(); db.refresh(m)
    return _mnt_dict(m)


@router.post("/status/announcements", status_code=201)
def create_announcement(body: AnnouncementCreate, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    a = Announcement(
        title=body.title, body=body.body, pinned=body.pinned,
        published_at=body.published_at or datetime.utcnow(), status="published",
    )
    db.add(a); db.commit(); db.refresh(a)
    return _ann_dict(a)


@router.patch("/status/announcements/{ann_id}")
def patch_announcement(ann_id: int, body: AnnouncementPatch, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    a = db.get(Announcement, ann_id)
    if not a:
        raise HTTPException(status_code=404, detail="announcement not found")
    if body.status is not None:
        if body.status not in _ANN_STATUS:
            raise HTTPException(status_code=422, detail="invalid status")
        a.status = body.status
    if body.title is not None:
        a.title = body.title
    if body.body is not None:
        a.body = body.body
    if body.pinned is not None:
        a.pinned = body.pinned
    db.commit(); db.refresh(a)
    return _ann_dict(a)
