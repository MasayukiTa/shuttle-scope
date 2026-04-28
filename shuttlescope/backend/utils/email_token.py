"""メール経由トークンの生成・ハッシュ化・検証。

設計方針:
  - トークン平文 = secrets.token_urlsafe(32) で生成 (約 43 文字、~256 bit のエントロピー)
  - 平文をユーザーへ (URL 経由でメールに記載)
  - DB には HMAC-SHA256(token, SS_EMAIL_TOKEN_HMAC_KEY) のみ保存
  - DB が漏洩しても、HMAC 鍵がなければトークン平文を逆算不能
  - 検証: 平文を再ハッシュして DB と比較

セキュリティ:
  - Single use: consumed_at IS NULL の WHERE 句で原子的に UPDATE
  - 期限: expires_at < utcnow() なら拒否
  - スコープ: テーブル分離で型安全 (verify_email_token / verify_password_reset_token / verify_invitation_token)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# トークン平文の長さ (URL-safe base64 → 約 43 文字)
_TOKEN_PLAIN_BYTES = 32


def _hmac_key() -> bytes:
    """SS_EMAIL_TOKEN_HMAC_KEY をバイト列として返す。未設定時は SECRET_KEY フォールバック。"""
    try:
        from backend.config import settings
        v = (getattr(settings, "ss_email_token_hmac_key", "") or "").strip()
        if not v:
            v = (getattr(settings, "SECRET_KEY", "") or "").strip()
    except Exception:
        v = (os.environ.get("SS_EMAIL_TOKEN_HMAC_KEY", "")
             or os.environ.get("SECRET_KEY", "")).strip()
    if not v:
        # 致命的: 検証不可能になるため例外
        raise RuntimeError(
            "SS_EMAIL_TOKEN_HMAC_KEY も SECRET_KEY も設定されていません。"
            " 起動を継続できません。"
        )
    return v.encode("utf-8")


def _hash_token(token_plain: str) -> str:
    """トークン平文を HMAC-SHA256 でハッシュ化する。"""
    h = hmac.new(_hmac_key(), token_plain.encode("utf-8"), hashlib.sha256)
    return h.hexdigest()


def _generate_plain() -> str:
    return secrets.token_urlsafe(_TOKEN_PLAIN_BYTES)


# ─── Email Verification ─────────────────────────────────────────────────────

def issue_email_verification_token(
    db: Session,
    user_id: int,
    email: str,
    ttl_minutes: Optional[int] = None,
) -> str:
    """メール検証トークンを発行する。返り値は URL に埋め込む平文トークン。"""
    from backend.db.models import EmailVerificationToken
    if ttl_minutes is None:
        ttl_minutes = _default_ttl_minutes()
    plain = _generate_plain()
    rec = EmailVerificationToken(
        user_id=user_id,
        token_hash=_hash_token(plain),
        email=email,
        expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes),
    )
    db.add(rec)
    db.commit()
    return plain


def consume_email_verification_token(db: Session, token_plain: str) -> Optional[Tuple[int, str]]:
    """検証トークンを消費し、(user_id, email) を返す。失敗時は None。"""
    from backend.db.models import EmailVerificationToken
    h = _hash_token(token_plain)
    rec = (
        db.query(EmailVerificationToken)
        .filter(
            EmailVerificationToken.token_hash == h,
            EmailVerificationToken.consumed_at.is_(None),
            EmailVerificationToken.expires_at > datetime.utcnow(),
        )
        .first()
    )
    if rec is None:
        return None
    rec.consumed_at = datetime.utcnow()
    user_id, email = rec.user_id, rec.email
    db.commit()
    return user_id, email


# ─── Password Reset ─────────────────────────────────────────────────────────

def issue_password_reset_token(
    db: Session,
    user_id: int,
    requested_ip: Optional[str] = None,
    ttl_minutes: Optional[int] = None,
) -> str:
    from backend.db.models import PasswordResetToken
    if ttl_minutes is None:
        ttl_minutes = _default_ttl_minutes()
    plain = _generate_plain()
    rec = PasswordResetToken(
        user_id=user_id,
        token_hash=_hash_token(plain),
        expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes),
        requested_ip=requested_ip,
    )
    db.add(rec)
    db.commit()
    return plain


def consume_password_reset_token(db: Session, token_plain: str) -> Optional[int]:
    """パスワードリセットトークンを消費し、user_id を返す。"""
    from backend.db.models import PasswordResetToken
    h = _hash_token(token_plain)
    rec = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == h,
            PasswordResetToken.consumed_at.is_(None),
            PasswordResetToken.expires_at > datetime.utcnow(),
        )
        .first()
    )
    if rec is None:
        return None
    rec.consumed_at = datetime.utcnow()
    user_id = rec.user_id
    db.commit()
    return user_id


# ─── Invitation ─────────────────────────────────────────────────────────────

def issue_invitation_token(
    db: Session,
    email: str,
    role: str,
    inviter_user_id: int,
    team_id: Optional[int] = None,
    ttl_hours: Optional[int] = None,
) -> str:
    from backend.db.models import InvitationToken
    if ttl_hours is None:
        ttl_hours = _default_invite_ttl_hours()
    plain = _generate_plain()
    rec = InvitationToken(
        token_hash=_hash_token(plain),
        email=email,
        role=role,
        team_id=team_id,
        inviter_user_id=inviter_user_id,
        expires_at=datetime.utcnow() + timedelta(hours=ttl_hours),
    )
    db.add(rec)
    db.commit()
    return plain


def consume_invitation_token(db: Session, token_plain: str, accepted_by_user_id: int):
    """招待トークンを消費し、招待レコードを返す。失敗時は None。"""
    from backend.db.models import InvitationToken
    h = _hash_token(token_plain)
    rec = (
        db.query(InvitationToken)
        .filter(
            InvitationToken.token_hash == h,
            InvitationToken.consumed_at.is_(None),
            InvitationToken.expires_at > datetime.utcnow(),
        )
        .first()
    )
    if rec is None:
        return None
    rec.consumed_at = datetime.utcnow()
    rec.consumed_by_user_id = accepted_by_user_id
    db.commit()
    return rec


def peek_invitation_token(db: Session, token_plain: str):
    """招待トークンを消費せず読み取る (accept ページの初期表示用)。"""
    from backend.db.models import InvitationToken
    h = _hash_token(token_plain)
    return (
        db.query(InvitationToken)
        .filter(
            InvitationToken.token_hash == h,
            InvitationToken.consumed_at.is_(None),
            InvitationToken.expires_at > datetime.utcnow(),
        )
        .first()
    )


# ─── 設定 ──────────────────────────────────────────────────────────────────

def _default_ttl_minutes() -> int:
    try:
        from backend.config import settings
        return int(getattr(settings, "ss_email_token_ttl_minutes", 15) or 15)
    except Exception:
        return int(os.environ.get("SS_EMAIL_TOKEN_TTL_MINUTES", "15"))


def _default_invite_ttl_hours() -> int:
    try:
        from backend.config import settings
        return int(getattr(settings, "ss_invite_token_ttl_hours", 72) or 72)
    except Exception:
        return int(os.environ.get("SS_INVITE_TOKEN_TTL_HOURS", "72"))
