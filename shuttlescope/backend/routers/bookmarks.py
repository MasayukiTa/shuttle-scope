"""U-001: イベントブックマーク / クリップ要求API（/api/bookmarks）

試合中・試合後のブックマーク管理。
- 手動ブックマーク（manual）: アナリストが任意タイミングで付与
- コーチ要求（coach_request）: コーチがコーチビューから「あとで見たい」を発火
- 自動統計（auto_stat）: 特定統計閾値到達時に自動生成
- クリップ要求（clip_request）: レビューキュー向けの明示的クリップ要求

試合後は GET /api/bookmarks?match_id=X でレビューキューとして使う。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import EventBookmark, Match
from backend.utils.auth import require_match_scope as _require_match_scope
from backend.utils.sync_meta import touch_sync_metadata, get_device_id

router = APIRouter()

VALID_TYPES = {"manual", "coach_request", "auto_stat", "clip_request"}
# coach_request はコーチのみ（WebSocket ブロードキャスト発火権限を制限）
_COACH_ONLY_TYPES = {"coach_request"}
# auto_stat は解析バックエンド（analyst/admin）のみが自動生成で付ける
_ANALYST_ONLY_TYPES = {"auto_stat"}


class BookmarkCreate(BaseModel):
    # extra (created_by_user_id 等) の silent drop を禁止
    model_config = {"extra": "forbid"}
    match_id: int
    rally_id: Optional[int] = None
    stroke_id: Optional[int] = None
    bookmark_type: str = "manual"
    # 動画タイムスタンプ: 0 秒 〜 24 時間以内に限定 (負数・10 年後を拒否)
    video_timestamp_sec: Optional[float] = Field(default=None, ge=0, le=86400)
    # note: 長さ制限 (DoS 対策、2500 文字通過していた実績を塞ぐ)
    note: Optional[str] = Field(default=None, max_length=2000)


@router.post("/bookmarks", status_code=201)
def create_bookmark(body: BookmarkCreate, request: Request, db: Session = Depends(get_db)):
    """ブックマーク追加"""
    match = db.get(Match, body.match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    if body.bookmark_type not in VALID_TYPES:
        raise HTTPException(status_code=422, detail=f"bookmark_type は {VALID_TYPES} のいずれかを指定してください")

    ctx = _require_match_scope(request, match, db)
    # coach_request は coach / analyst / admin のみ（WS ブロードキャスト発火の悪用を防ぐ）。
    # analyst も許可するのは、ローカル Electron のアナリストがコーチ視点の
    # クリップ要求を代行投入できるようにするため。
    if body.bookmark_type in _COACH_ONLY_TYPES and not (ctx.is_coach or ctx.is_analyst or ctx.is_admin):
        raise HTTPException(status_code=403, detail="coach_request はコーチ / analyst のみ作成できます")
    # auto_stat は analyst / admin のみ（自動統計ラベルのなりすまし防止）
    if body.bookmark_type in _ANALYST_ONLY_TYPES and not (ctx.is_analyst or ctx.is_admin):
        raise HTTPException(status_code=403, detail="auto_stat は analyst のみ作成できます")

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
    request: Request,
    bookmark_type: Optional[str] = None,
    reviewed_only: bool = False,
    unreviewed_only: bool = False,
    db: Session = Depends(get_db),
):
    """ブックマーク一覧（レビューキューとして使用）"""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    _require_match_scope(request, match, db)
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
def mark_reviewed(bookmark_id: int, request: Request, db: Session = Depends(get_db)):
    """確認済みマーク"""
    bm = db.get(EventBookmark, bookmark_id)
    if not bm:
        raise HTTPException(status_code=404, detail="ブックマークが見つかりません")
    match = db.get(Match, bm.match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    _require_match_scope(request, match, db)
    bm.is_reviewed = True
    touch_sync_metadata(bm, device_id=get_device_id(db))
    db.commit()
    return {"success": True}


@router.delete("/bookmarks/{bookmark_id}")
def delete_bookmark(bookmark_id: int, request: Request, db: Session = Depends(get_db)):
    bm = db.get(EventBookmark, bookmark_id)
    if not bm or bm.deleted_at is not None:
        raise HTTPException(status_code=404, detail="ブックマークが見つかりません")
    match = db.get(Match, bm.match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    ctx = _require_match_scope(request, match, db)
    # player は削除不可（他者の自動統計等を消すのを防ぐ）。coach は削除可だが
    # analyst / admin 以外は自チームスコープ内のみ（_require_match_scope で確認済み）。
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="このブックマークを削除する権限がありません")
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
