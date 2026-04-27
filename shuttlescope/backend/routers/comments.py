"""S-003: コメント・タグ共有API（/api/comments）

試合 / セット / ラリー / ストロークへのコメントを付与する。
セッション参加者全員が閲覧・投稿できる。重要フラグ付きコメントはセット間サマリーへ集約される。
"""
import re as _re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Comment, Match
from backend.utils.auth import get_auth, require_match_scope as _require_match_scope
from backend.utils.sync_meta import touch_sync_metadata, get_device_id

router = APIRouter()


class CommentCreate(BaseModel):
    # extra フィールド (author_role / user_id 等) の silent drop を禁止
    model_config = {"extra": "forbid"}
    match_id: int
    # text 長さ制限 (DoS 対策、10万文字を容認した実例を塞ぐ)
    text: str = Field(..., min_length=1, max_length=5000)
    session_id: Optional[int] = None
    set_id: Optional[int] = None
    rally_id: Optional[int] = None
    stroke_id: Optional[int] = None
    is_flagged: bool = False

    @field_validator("text", mode="before")
    @classmethod
    def _sanitize_text(cls, v):
        if v is None:
            return v
        v = str(v)
        v = v.replace("\x00", "")
        v = _re.sub(r"<[^>]*>", "", v)
        return v


# Per-user comment post rate limit (DoS / spam 対策)
# 60 秒に 1 user あたり最大 20 コメント (analyst の業務で十分、50 連投を防ぐ)
import threading as _th_c
import time as _t_c
_comment_post_counters: dict[int, list[float]] = {}
_comment_post_lock = _th_c.Lock()
_COMMENT_WINDOW_SEC = 60
_COMMENT_MAX_PER_WINDOW = 20


@router.post("/comments", status_code=201)
def create_comment(body: CommentCreate, request: Request, db: Session = Depends(get_db)):
    """コメント投稿。author_role はサーバ側で JWT から決定しクライアント入力を無視する。"""
    match = db.get(Match, body.match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    ctx = _require_match_scope(request, match, db)
    # Phase B: 多層防御 — team_id ベースのアクセス制御を追加 (4-1)
    from backend.utils.auth import user_can_access_match
    if not user_can_access_match(ctx, match):
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    # DoS 対策: user あたり 60 秒に 20 comment 上限
    if ctx.user_id:
        now = _t_c.time()
        with _comment_post_lock:
            ts = _comment_post_counters.setdefault(ctx.user_id, [])
            cutoff = now - _COMMENT_WINDOW_SEC
            ts[:] = [t for t in ts if t >= cutoff]
            if len(ts) >= _COMMENT_MAX_PER_WINDOW:
                raise HTTPException(status_code=429, detail="コメント投稿が多すぎます。しばらく待ってから再試行してください。")
            ts.append(now)

    # author_role は必ず認証済みコンテキストから決定する（なりすまし防止）
    author_role = ctx.role or "unknown"
    data = body.model_dump()
    data["author_role"] = author_role
    # Phase B-12: 書き込みチームを ctx から強制注入（リーク防止）
    data["team_id"] = ctx.team_id

    comment = Comment(**data)
    db.add(comment)
    payload = {"match_id": body.match_id, "text": body.text, "author_role": author_role}
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
    request: Request,
    rally_id: Optional[int] = None,
    flagged_only: bool = False,
    db: Session = Depends(get_db),
):
    """コメント一覧（match_id 必須）。match スコープ認可 + Phase B-12 チーム境界を適用。"""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    ctx = _require_match_scope(request, match, db)
    q = db.query(Comment).filter(Comment.match_id == match_id, Comment.deleted_at.is_(None))
    if not ctx.is_admin:
        q = q.filter(or_(Comment.team_id.is_(None), Comment.team_id == ctx.team_id))
    if rally_id is not None:
        q = q.filter(Comment.rally_id == rally_id)
    if flagged_only:
        q = q.filter(Comment.is_flagged.is_(True))
    comments = q.order_by(Comment.created_at).all()
    return {"success": True, "data": [_comment_to_dict(c) for c in comments]}


@router.patch("/comments/{comment_id}/flag")
def toggle_flag(comment_id: int, request: Request, db: Session = Depends(get_db)):
    """重要フラグのトグル。match スコープ認可を適用する。"""
    comment = db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="コメントが見つかりません")
    match = db.get(Match, comment.match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="コメントが見つかりません")
    ctx = _require_match_scope(request, match, db)
    # player は他人のコメントを flag できない
    if ctx.is_player and comment.author_role != "player":
        raise HTTPException(status_code=403, detail="このコメントを変更する権限がありません")
    comment.is_flagged = not comment.is_flagged
    touch_sync_metadata(comment, device_id=get_device_id(db))
    db.commit()
    return {"success": True, "data": _comment_to_dict(comment)}


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, request: Request, db: Session = Depends(get_db)):
    comment = db.get(Comment, comment_id)
    if not comment or comment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="コメントが見つかりません")
    match = db.get(Match, comment.match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="コメントが見つかりません")
    ctx = _require_match_scope(request, match, db)
    # player / coach は自分（同ロール）のコメントのみ削除可能、analyst / admin は全て削除可能
    if not (ctx.is_admin or ctx.is_analyst):
        if comment.author_role != ctx.role:
            raise HTTPException(status_code=403, detail="このコメントを削除する権限がありません")
    from datetime import datetime
    comment.deleted_at = datetime.utcnow()
    touch_sync_metadata(comment, device_id=get_device_id(db))
    db.commit()
    # audit log: 他 user のコメントを analyst/admin が削除した場合 forensic 用に記録
    try:
        from backend.utils.access_log import log_access as _log
        _log(db, "comment_deleted", user_id=ctx.user_id,
             resource_type="comment", resource_id=comment_id,
             details={"actor_role": ctx.role, "author_role": comment.author_role,
                      "match_id": comment.match_id})
    except Exception:
        pass
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
