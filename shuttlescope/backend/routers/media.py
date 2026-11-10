"""メディア (SFU/LiveKit) 関連 API。

`POST /api/media/token`:
  認証済みユーザにのみ LiveKit access token を発行する**セキュリティゲート**。
  これにより、インターネットの匿名スキャナは token を得られず room に join 不可。
  - 認証必須 (匿名は 401)
  - operator ロールは privileged role (admin/analyst/coach) 限定 (それ以外 403)
  - 対象 session が active であること (404)
  - camera / viewer は /sessions/{code}/join で発行された participant 資格
    (participant_id + participant_token) と operator 承認を要求 (403)
  - LiveKit 未設定なら 503
設計: docs/validation/2026-06-01_rtmp_sfu_media_plane_design.md
セキュリティ: docs/validation/2026-06-01_selfhost_sfu_security_hardening.md
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, SessionParticipant, SharedSession
from backend.utils.auth import get_auth, require_match_scope
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
    # camera / viewer は /sessions/{code}/join が発行した参加資格を必須にする。
    # session password を検証済みの参加者だけが映像を送受信できるようにするため。
    participant_id: Optional[int] = Field(default=None, ge=1, le=2_147_483_647)
    participant_token: Optional[str] = Field(default=None, min_length=16, max_length=256)


def _require_participant_credential(
    body: MediaTokenRequest, sess: SharedSession, db: Session
) -> SessionParticipant:
    """camera / viewer 用: join 済み (password 検証済み) の承認された参加者を要求する。

    欠落・別セッション・トークン不一致は区別できない同一の 403 にする
    (参加者 ID の存在確認 oracle にしない)。ws-ticket と同じ承認条件を課す。
    """
    from backend.routers.sessions import _participant_token_valid

    denied = HTTPException(status_code=403, detail="participant credential required")
    if body.participant_id is None or not body.participant_token:
        raise denied
    participant = db.get(SessionParticipant, body.participant_id)
    if (
        participant is None
        or participant.session_id != sess.id
        or not _participant_token_valid(participant, body.participant_token)
    ):
        raise denied
    if participant.approval_status != "approved":
        raise HTTPException(status_code=403, detail="participant not approved")
    if body.role == "camera" and participant.source_capability != "camera":
        raise HTTPException(status_code=403, detail="participant is not a camera")
    if body.role == "viewer" and participant.viewer_permission == "blocked":
        raise HTTPException(status_code=403, detail="viewer access blocked")
    return participant


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
    # 4b. session -> match の team scope (他チームのライブ映像室に入れない)。
    #     admin 素通し / coach・analyst は自チーム試合 / player は出場試合のみ (role 問わず)。
    match = db.get(Match, sess.match_id) if sess.match_id is not None else None
    if match is None:
        raise HTTPException(status_code=404, detail="session not found or inactive")
    require_match_scope(request, match, db)
    # 4c. camera / viewer は join (session password 検証) 済みの承認された参加者のみ。
    #     JWT + active な session_code を知っているだけでは映像室に入れない。
    if body.role in ("camera", "viewer"):
        _require_participant_credential(body, sess, db)
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
