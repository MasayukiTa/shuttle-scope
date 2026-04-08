"""S-003: コメント・タグ共有API（/api/comments）

試合 / セット / ラリー / ストロークへのコメントを付与する。
セッション参加者全員が閲覧・投稿できる。重要フラグ付きコメントはセット間サマリーへ集約される。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Comment, Match
from backend.utils.sync_meta import touch_sync_metadata, get_device_id

router = APIRouter()


class CommentCreate(BaseModel):
    match_id: int
    text: str
    author_role: str = "analyst"
    session_id: Optional[int] = None
    set_id: Optional[int] = None
    rally_id: Optional[int] = None
    stroke_id: Optional[int] = None
    is_flagged: bool = False


@router.post("/comments", status_code=201)
def create_comment(body: CommentCreate, db: Session = Depends(get_db)):
    """コメント投稿"""
    if not db.get(Match, body.match_id):
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    comment = Comment(**body.model_dump())
    db.add(comment)
    payload = {"match_id": body.match_id, "text": body.text, "author_role": body.author_role}
    touch_sync_metadata(comment, payload_like=payload, device_id=get_device_id(db))
    db.commit()
    db.refresh(comment)

    # アクティブセッションへブロードキャスト（非同期にしない — FastAPIが sync def を threadpool で実行）
    import asyncio
    from backend.ws.live import manager
    from backend.db.models import SharedSession

    sessions = (
        db.query(SharedSession)
        .filter(SharedSession.match_id == body.match_id, SharedSession.is_active.is_(True))
        .all()
    )
    payload = {
        "type": "comment",
        "data": _comment_to_dict(comment),
    }
    for s in sessions:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(manager.broadcast(s.session_code, payload))
        except Exception:
            pass

    return {"success": True, "data": _comment_to_dict(comment)}


@router.get("/comments")
def list_comments(
    match_id: int,
    rally_id: Optional[int] = None,
    flagged_only: bool = False,
    db: Session = Depends(get_db),
):
    """コメント一覧（match_id 必須）"""
    q = db.query(Comment).filter(Comment.match_id == match_id, Comment.deleted_at.is_(None))
    if rally_id is not None:
        q = q.filter(Comment.rally_id == rally_id)
    if flagged_only:
        q = q.filter(Comment.is_flagged.is_(True))
    comments = q.order_by(Comment.created_at).all()
    return {"success": True, "data": [_comment_to_dict(c) for c in comments]}


@router.patch("/comments/{comment_id}/flag")
def toggle_flag(comment_id: int, db: Session = Depends(get_db)):
    """重要フラグのトグル"""
    comment = db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="コメントが見つかりません")
    comment.is_flagged = not comment.is_flagged
    touch_sync_metadata(comment, device_id=get_device_id(db))
    db.commit()
    return {"success": True, "data": _comment_to_dict(comment)}


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, db: Session = Depends(get_db)):
    comment = db.get(Comment, comment_id)
    if not comment or comment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="コメントが見つかりません")
    from datetime import datetime
    comment.deleted_at = datetime.utcnow()
    touch_sync_metadata(comment, device_id=get_device_id(db))
    db.commit()
    return {"success": True}


def _comment_to_dict(c: Comment) -> dict:
    return {
        "id": c.id,
        "match_id": c.match_id,
        "set_id": c.set_id,
        "rally_id": c.rally_id,
        "stroke_id": c.stroke_id,
        "session_id": c.session_id,
        "author_role": c.author_role,
        "text": c.text,
        "is_flagged": c.is_flagged,
        "created_at": c.created_at.isoformat(),
    }
