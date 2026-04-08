"""U-001: イベントブックマーク / クリップ要求API（/api/bookmarks）

試合中・試合後のブックマーク管理。
- 手動ブックマーク（manual）: アナリストが任意タイミングで付与
- コーチ要求（coach_request）: コーチがコーチビューから「あとで見たい」を発火
- 自動統計（auto_stat）: 特定統計閾値到達時に自動生成
- クリップ要求（clip_request）: レビューキュー向けの明示的クリップ要求

試合後は GET /api/bookmarks?match_id=X でレビューキューとして使う。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import EventBookmark, Match
from backend.utils.sync_meta import touch_sync_metadata, get_device_id

router = APIRouter()

VALID_TYPES = {"manual", "coach_request", "auto_stat", "clip_request"}


class BookmarkCreate(BaseModel):
    match_id: int
    rally_id: Optional[int] = None
    stroke_id: Optional[int] = None
    bookmark_type: str = "manual"
    video_timestamp_sec: Optional[float] = None
    note: Optional[str] = None


@router.post("/bookmarks", status_code=201)
def create_bookmark(body: BookmarkCreate, db: Session = Depends(get_db)):
    """ブックマーク追加"""
    if not db.get(Match, body.match_id):
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    if body.bookmark_type not in VALID_TYPES:
        raise HTTPException(status_code=422, detail=f"bookmark_type は {VALID_TYPES} のいずれかを指定してください")

    bm = EventBookmark(**body.model_dump())
    db.add(bm)
    payload = {"match_id": body.match_id, "bookmark_type": body.bookmark_type, "rally_id": body.rally_id}
    touch_sync_metadata(bm, payload_like=payload, device_id=get_device_id(db))
    db.commit()
    db.refresh(bm)

    # コーチ要求の場合はアナリストへ通知ブロードキャスト
    if body.bookmark_type == "coach_request":
        import asyncio
        from backend.ws.live import manager
        from backend.db.models import SharedSession

        sessions = (
            db.query(SharedSession)
            .filter(SharedSession.match_id == body.match_id, SharedSession.is_active.is_(True))
            .all()
        )
        payload = {"type": "clip_request", "data": _bm_to_dict(bm)}
        for s in sessions:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(manager.broadcast(s.session_code, payload))
            except Exception:
                pass

    return {"success": True, "data": _bm_to_dict(bm)}


@router.get("/bookmarks")
def list_bookmarks(
    match_id: int,
    bookmark_type: Optional[str] = None,
    reviewed_only: bool = False,
    unreviewed_only: bool = False,
    db: Session = Depends(get_db),
):
    """ブックマーク一覧（レビューキューとして使用）"""
    q = db.query(EventBookmark).filter(EventBookmark.match_id == match_id, EventBookmark.deleted_at.is_(None))
    if bookmark_type:
        q = q.filter(EventBookmark.bookmark_type == bookmark_type)
    if reviewed_only:
        q = q.filter(EventBookmark.is_reviewed.is_(True))
    if unreviewed_only:
        q = q.filter(EventBookmark.is_reviewed.is_(False))
    bms = q.order_by(EventBookmark.created_at).all()
    return {"success": True, "data": [_bm_to_dict(b) for b in bms]}


@router.patch("/bookmarks/{bookmark_id}/reviewed")
def mark_reviewed(bookmark_id: int, db: Session = Depends(get_db)):
    """確認済みマーク"""
    bm = db.get(EventBookmark, bookmark_id)
    if not bm:
        raise HTTPException(status_code=404, detail="ブックマークが見つかりません")
    bm.is_reviewed = True
    touch_sync_metadata(bm, device_id=get_device_id(db))
    db.commit()
    return {"success": True}


@router.delete("/bookmarks/{bookmark_id}")
def delete_bookmark(bookmark_id: int, db: Session = Depends(get_db)):
    bm = db.get(EventBookmark, bookmark_id)
    if not bm or bm.deleted_at is not None:
        raise HTTPException(status_code=404, detail="ブックマークが見つかりません")
    from datetime import datetime
    bm.deleted_at = datetime.utcnow()
    touch_sync_metadata(bm, device_id=get_device_id(db))
    db.commit()
    return {"success": True}


def _bm_to_dict(bm: EventBookmark) -> dict:
    return {
        "id": bm.id,
        "match_id": bm.match_id,
        "rally_id": bm.rally_id,
        "stroke_id": bm.stroke_id,
        "bookmark_type": bm.bookmark_type,
        "video_timestamp_sec": bm.video_timestamp_sec,
        "note": bm.note,
        "is_reviewed": bm.is_reviewed,
        "created_at": bm.created_at.isoformat(),
    }
