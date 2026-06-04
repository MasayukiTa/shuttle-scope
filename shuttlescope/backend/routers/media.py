"""メディア (SFU/LiveKit) 関連 API。

`POST /api/media/token`:
  認証済みユーザにのみ LiveKit access token を発行する**セキュリティゲート**。
  これにより、インターネットの匿名スキャナは token を得られず room に join 不可。
  - 認証必須 (匿名は 401)
  - operator ロールは privileged role (admin/analyst/coach) 限定 (それ以外 403)
  - 対象 session が active であること (404)
  - LiveKit 未設定なら 503
設計: docs/validation/2026-06-01_rtmp_sfu_media_plane_design.md
セキュリティ: docs/validation/2026-06-01_selfhost_sfu_security_hardening.md
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import SharedSession
from backend.utils.auth import get_auth
from backend.services.livekit_media import (
    issue_access_token,
    load_config,
    room_name_for,
)

router = APIRouter()

_PRIVILEGED_ROLES = {"admin", "analyst", "coach"}
_VALID_ROLES = {"operator", "camera", "viewer"}


class MediaTokenRequest(BaseModel):
    session_code: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=16)


@router.post("/media/token")
def media_token(body: MediaTokenRequest, request: Request, db: Session = Depends(get_db)):
    # 1. role 妥当性 (認証前に弾く)
    if body.role not in _VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"invalid role: {body.role!r}")
    # 2. 認証必須 (匿名は role=None)
    ctx = get_auth(request)
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="authentication required")
    # 3. operator は privileged role 限定
    if body.role == "operator" and ctx.role not in _PRIVILEGED_ROLES:
        raise HTTPException(status_code=403, detail="operator role requires privileged account")
    # 4. session が active か
    sess = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == body.session_code, SharedSession.is_active.is_(True))
        .first()
    )
    if not sess:
        raise HTTPException(status_code=404, detail="session not found or inactive")
    # 5. LiveKit 設定済みか
    cfg = load_config()
    if not cfg.configured:
        raise HTTPException(status_code=503, detail="media backend (LiveKit) not configured")
    # 6. token 発行 (identity は user_id でユニーク化、room は session に固定)
    identity = f"{body.role}-{ctx.user_id or 'anon'}"
    token = issue_access_token(identity, body.session_code, body.role, cfg=cfg)  # type: ignore[arg-type]
    return {
        "url": cfg.url,
        "room": room_name_for(body.session_code),
        "identity": identity,
        "token": token,
    }
