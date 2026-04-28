"""メール経由のセルフサービス認証ルーター (M-A4)。

エンドポイント:
  POST /api/auth/register                    新規登録 (email + password + Turnstile)
  POST /api/auth/email/resend_verification   検証メール再送 (要ログイン)
  GET  /api/auth/email/verify                リンク検証 (?token=...)
  POST /api/auth/password/request_reset      リセットメール送信要求 (email + Turnstile)
  POST /api/auth/password/reset              token + 新 password で実リセット
  POST /api/auth/invitation/create           招待発行 (admin/coach)
  GET  /api/auth/invitation/peek             招待トークン情報を取得 (accept ページ初期表示)
  POST /api/auth/invitation/accept           招待トークンでアカウント作成

セキュリティ:
  - register / request_reset は email 存在に関わらず同じレスポンス (列挙防御)
  - rate limit は既存 middleware で IP/email 単位
  - access_log に各イベントを記録
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import User
from backend.utils.access_log import log_access
from backend.utils.auth import get_auth
from backend.utils.email_token import (
    issue_email_verification_token,
    consume_email_verification_token,
    issue_password_reset_token,
    consume_password_reset_token,
    issue_invitation_token,
    consume_invitation_token,
    peek_invitation_token,
)
from backend.utils.turnstile import verify_turnstile

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth_email"])

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-.]{3,64}$")


# ─── スキーマ ───────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: Optional[str] = Field(None, max_length=100)
    turnstile_token: Optional[str] = Field(None, max_length=2048)


class PasswordResetRequest(BaseModel):
    email: EmailStr
    turnstile_token: Optional[str] = Field(None, max_length=2048)


class PasswordResetConfirm(BaseModel):
    token: str = Field(..., min_length=10, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=128)


class InvitationCreateRequest(BaseModel):
    email: EmailStr
    role: str = Field("analyst", pattern=r"^(analyst|coach|player)$")
    team_id: Optional[int] = Field(None, ge=1, le=2_147_483_647)


class InvitationAcceptRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=200)
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)
    display_name: Optional[str] = Field(None, max_length=100)


# ─── ヘルパー ─────────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    cf = request.headers.get("CF-Connecting-IP", "").strip()
    if cf:
        return cf[:64]
    return (request.client.host if request.client else "")[:64]


def _app_base_url() -> str:
    try:
        from backend.config import settings
        return (getattr(settings, "ss_app_base_url", "") or "https://app.shuttle-scope.com").rstrip("/")
    except Exception:
        import os
        return (os.environ.get("SS_APP_BASE_URL", "") or "https://app.shuttle-scope.com").rstrip("/")


def _hash_password_or_422(password: str) -> str:
    """既存の auth.py 内ヘルパーを再利用するため遅延 import。"""
    from backend.routers.auth import _hash_password, _validate_password_strength
    _validate_password_strength(password)
    return _hash_password(password)


def _send_email_safe(to: str, subject: str, body: str, tag: str) -> None:
    """例外を吸収してメール送信する。失敗してもユーザーフローは止めない。"""
    try:
        from backend.services.mailer import get_mailer
        from backend.services.mailer.base import MailMessage
        mailer = get_mailer()
        mailer.send(MailMessage(to=[to], subject=subject, text_body=body, tags=[tag]))
    except Exception as exc:
        logger.error("[auth_email] mail send failed (%s): %s", tag, exc)


# ─── 1. Register ─────────────────────────────────────────────────────────────

@router.post("/auth/register", status_code=201)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """新規ユーザー登録。

    - username + email + password + Turnstile
    - 即座にメール検証トークン発行 → メール送信
    - email_verified_at は None (検証メールリンク踏むまで未検証)
    """
    ip = _client_ip(request)
    ok, reason = verify_turnstile(body.turnstile_token, ip)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    if not _USERNAME_RE.match(body.username):
        raise HTTPException(status_code=422, detail="username の形式が不正です (3-64 文字、英数 _ - .)")

    # username / email 重複チェック
    existing = (
        db.query(User)
        .filter((User.username == body.username) | (User.email == body.email))
        .first()
    )
    if existing is not None:
        # 列挙防御: 既存でも同じ「成功風」レスポンスを返す
        # 実際のメールは送らない (既存ユーザに通知してしまうので)
        log_access(db, "register_duplicate", details={"username": body.username, "ip": ip})
        return {"success": True, "data": {"user_id": None}}

    hashed = _hash_password_or_422(body.password)
    user = User(
        username=body.username,
        email=body.email,
        hashed_credential=hashed,
        display_name=body.display_name,
        role="analyst",  # デフォルト role (admin が後で変更可)
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 検証トークン発行 + メール送信
    token = issue_email_verification_token(db, user.id, body.email)
    verify_url = f"{_app_base_url()}/verify?token={token}"
    _send_email_safe(
        body.email,
        "ShuttleScope メールアドレス確認",
        f"以下のリンクをクリックして、メールアドレスの確認を完了してください:\n\n{verify_url}\n\n"
        f"このリンクは {15} 分間有効です。\n"
        f"心当たりがない場合はこのメールを無視してください。",
        tag="email_verify",
    )
    log_access(db, "register", user_id=user.id, ip_addr=ip,
               details={"email_domain": body.email.split("@")[-1]})
    return {"success": True, "data": {"user_id": user.id}}


# ─── 2. Email verification ───────────────────────────────────────────────────

@router.get("/auth/email/verify")
def verify_email(token: str = Query(..., min_length=10, max_length=200),
                 request: Request = None, db: Session = Depends(get_db)):
    """メール内のリンクを踏んだ時の検証エンドポイント。"""
    result = consume_email_verification_token(db, token)
    if result is None:
        raise HTTPException(status_code=400, detail="トークンが無効または期限切れです")
    user_id, email = result
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    user.email = email
    user.email_verified_at = datetime.utcnow()
    db.commit()
    log_access(db, "email_verified", user_id=user_id,
               ip_addr=_client_ip(request) if request else None)
    return {"success": True, "data": {"verified_email": email}}


@router.post("/auth/email/resend_verification")
def resend_verification(request: Request, db: Session = Depends(get_db)):
    """ログイン中ユーザーのメール検証リンクを再送する。"""
    ctx = get_auth(request)
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="認証が必要です")
    user = db.get(User, ctx.user_id)
    if user is None or not user.email:
        raise HTTPException(status_code=400, detail="メールアドレスが登録されていません")
    if user.email_verified_at is not None:
        return {"success": True, "data": {"already_verified": True}}
    token = issue_email_verification_token(db, user.id, user.email)
    verify_url = f"{_app_base_url()}/verify?token={token}"
    _send_email_safe(
        user.email,
        "ShuttleScope メールアドレス確認 (再送)",
        f"以下のリンクをクリックして確認を完了してください:\n\n{verify_url}",
        tag="email_verify_resend",
    )
    log_access(db, "email_verify_resend", user_id=user.id)
    return {"success": True, "data": {"sent": True}}


# ─── 3. Password reset ──────────────────────────────────────────────────────

@router.post("/auth/password/request_reset")
def request_password_reset(body: PasswordResetRequest, request: Request,
                           db: Session = Depends(get_db)):
    """パスワードリセットメールを送信する。

    列挙防御: email 存在に関わらず同じレスポンスを返す。
    """
    ip = _client_ip(request)
    ok, reason = verify_turnstile(body.turnstile_token, ip)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    user = db.query(User).filter(User.email == body.email).first()
    if user is not None:
        token = issue_password_reset_token(db, user.id, requested_ip=ip)
        reset_url = f"{_app_base_url()}/password/reset-confirm?token={token}"
        _send_email_safe(
            body.email,
            "ShuttleScope パスワードリセット",
            f"以下のリンクから新しいパスワードを設定してください:\n\n{reset_url}\n\n"
            f"このリンクは 15 分間有効です。\n"
            f"心当たりがない場合はこのメールを無視してください。",
            tag="password_reset",
        )
        log_access(db, "password_reset_requested", user_id=user.id, ip_addr=ip)
    else:
        log_access(db, "password_reset_unknown_email", ip_addr=ip,
                   details={"email_domain": body.email.split("@")[-1]})
    # 列挙防御: 常に成功風レスポンス
    return {"success": True, "data": {"sent": True}}


@router.post("/auth/password/reset")
def reset_password(body: PasswordResetConfirm, request: Request,
                   db: Session = Depends(get_db)):
    """token + 新 password で実リセット。"""
    user_id = consume_password_reset_token(db, body.token)
    if user_id is None:
        raise HTTPException(status_code=400, detail="トークンが無効または期限切れです")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    user.hashed_credential = _hash_password_or_422(body.new_password)
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
    log_access(db, "password_reset_completed", user_id=user_id, ip_addr=_client_ip(request))
    return {"success": True, "data": {"user_id": user_id}}


# ─── 4. Invitation ──────────────────────────────────────────────────────────

@router.post("/auth/invitation/create", status_code=201)
def create_invitation(body: InvitationCreateRequest, request: Request,
                      db: Session = Depends(get_db)):
    """admin / coach が新規メンバーを招待する。"""
    ctx = get_auth(request)
    if not (ctx.is_admin or ctx.role == "coach"):
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    # coach は player のみ招待可
    if not ctx.is_admin and body.role != "player":
        raise HTTPException(status_code=403, detail="coach は player のみ招待できます")
    # team_id 妥当性: coach は自チームのみ
    if not ctx.is_admin and body.team_id is not None and body.team_id != ctx.team_id:
        raise HTTPException(status_code=403, detail="他チームには招待できません")

    token = issue_invitation_token(
        db, body.email, body.role, ctx.user_id,
        team_id=(body.team_id if body.team_id is not None else ctx.team_id),
    )
    accept_url = f"{_app_base_url()}/invite?token={token}"
    _send_email_safe(
        body.email,
        "ShuttleScope への招待",
        f"ShuttleScope に招待されました ({body.role}).\n\n"
        f"以下のリンクからアカウントを作成してください:\n\n{accept_url}\n\n"
        f"このリンクは 72 時間有効です。",
        tag="invitation",
    )
    log_access(db, "invitation_created", user_id=ctx.user_id,
               details={"email_domain": body.email.split("@")[-1], "role": body.role})
    return {"success": True, "data": {"sent": True}}


@router.get("/auth/invitation/peek")
def peek_invitation(token: str = Query(..., min_length=10, max_length=200),
                    db: Session = Depends(get_db)):
    """招待トークンの内容を読み取る (accept ページの初期表示用)。

    トークンを消費しない。"""
    rec = peek_invitation_token(db, token)
    if rec is None:
        raise HTTPException(status_code=400, detail="トークンが無効または期限切れです")
    return {
        "success": True,
        "data": {
            "email": rec.email,
            "role": rec.role,
            "team_id": rec.team_id,
            "expires_at": rec.expires_at.isoformat(),
        },
    }


@router.post("/auth/invitation/accept", status_code=201)
def accept_invitation(body: InvitationAcceptRequest, request: Request,
                      db: Session = Depends(get_db)):
    """招待トークンで新規アカウントを作成する。"""
    if not _USERNAME_RE.match(body.username):
        raise HTTPException(status_code=422, detail="username の形式が不正です")

    rec = peek_invitation_token(db, body.token)
    if rec is None:
        raise HTTPException(status_code=400, detail="トークンが無効または期限切れです")

    # username / email 重複
    existing = (
        db.query(User)
        .filter((User.username == body.username) | (User.email == rec.email))
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="username または email が既に使用されています")

    hashed = _hash_password_or_422(body.password)
    user = User(
        username=body.username,
        email=rec.email,
        hashed_credential=hashed,
        display_name=body.display_name,
        role=rec.role,
        team_id=rec.team_id,
        email_verified_at=datetime.utcnow(),  # 招待リンク経由なので検証済み扱い
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # token 消費
    consume_invitation_token(db, body.token, accepted_by_user_id=user.id)
    log_access(db, "invitation_accepted", user_id=user.id,
               details={"role": rec.role, "inviter_user_id": rec.inviter_user_id})
    return {"success": True, "data": {"user_id": user.id, "role": user.role}}
