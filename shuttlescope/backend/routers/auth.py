"""Authentication and user-management routes."""

import base64
import hashlib
import hmac as _hmac_mod
import logging
import os
import re as _re
import struct
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

import bcrypt as _bcrypt_lib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db.models import Player, PlayerPageAccess, User

GRANTABLE_PAGES = {"prediction", "expert_labeler"}

_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_MINUTES = 30
_PASSWORD_MIN_LENGTH = 12

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_ID_MIN_LENGTH = 6
LOGIN_ID_MAX_LENGTH = 19


# ── パスワードユーティリティ ──────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    return _bcrypt_lib.hashpw(password.encode("utf-8"), _bcrypt_lib.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    try:
        return _bcrypt_lib.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _hash_user_credential(password: Optional[str], pin: Optional[str]) -> Optional[str]:
    secret = (password or pin or "").strip()
    if not secret:
        return None
    return _hash_password(secret)


def _validate_password_strength(password: str) -> None:
    """パスワード強度を検証する。不足の場合 HTTPException(422) を送出。"""
    if len(password) < _PASSWORD_MIN_LENGTH:
        raise HTTPException(422, f"パスワードは{_PASSWORD_MIN_LENGTH}文字以上が必要です")
    if not _re.search(r'[a-z]', password):
        raise HTTPException(422, "パスワードに小文字を含めてください")
    if not _re.search(r'[A-Z]', password):
        raise HTTPException(422, "パスワードに大文字を含めてください")
    if not _re.search(r'\d', password):
        raise HTTPException(422, "パスワードに数字を含めてください")
    if not _re.search(r'[!@#$%^&*()\-_=+\[\]{}|;:,.<>?/~`]', password):
        raise HTTPException(422, "パスワードに記号を含めてください (!@#$% 等)")


# ── TOTP（標準ライブラリのみ実装、pyotp 不要） ───────────────────────────────

def _totp_generate_secret() -> str:
    """20バイトのランダムシークレットを base32 エンコードで返す。"""
    return base64.b32encode(os.urandom(20)).decode("utf-8").rstrip("=")


def _hotp_value(secret: str, counter: int) -> int:
    padding = "=" * (-len(secret) % 8)
    key = base64.b32decode(secret.upper() + padding)
    msg = struct.pack(">Q", counter)
    h = _hmac_mod.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset: offset + 4])[0] & 0x7FFFFFFF
    return code % 1_000_000


def _verify_totp(secret: str, code: str) -> bool:
    """前後1ウィンドウ（±30秒）を許容してTOTPコードを検証する。"""
    try:
        input_code = int(code.strip())
    except (ValueError, TypeError):
        return False
    t = int(time.time()) // 30
    return any(_hotp_value(secret, t + w) == input_code for w in (-1, 0, 1))


def _totp_uri(secret: str, username: str) -> str:
    issuer = "ShuttleScope"
    return (
        f"otpauth://totp/{urllib.parse.quote(issuer)}:{urllib.parse.quote(username)}"
        f"?secret={secret}&issuer={urllib.parse.quote(issuer)}&algorithm=SHA1&digits=6&period=30"
    )


# ── ログインID バリデーション ─────────────────────────────────────────────────

def _normalize_login_id(value: Optional[str]) -> str:
    return (value or "").strip()


def _validate_login_id(login_id: str) -> str:
    normalized = _normalize_login_id(login_id)
    if not (LOGIN_ID_MIN_LENGTH <= len(normalized) <= LOGIN_ID_MAX_LENGTH):
        raise HTTPException(
            status_code=422,
            detail=f"login_id must be between {LOGIN_ID_MIN_LENGTH} and {LOGIN_ID_MAX_LENGTH} characters",
        )
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if any(ch not in allowed for ch in normalized):
        raise HTTPException(
            status_code=422,
            detail="login_id may contain only letters, numbers, hyphen, and underscore",
        )
    return normalized


def _get_ip(request: Request) -> Optional[str]:
    # control_plane._client_ip と同じロジック（CF-Connecting-IP 優先）
    cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
    if cf_ip:
        return cf_ip
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ── アカウントロックアウト ────────────────────────────────────────────────────

def _check_lockout(user: User) -> None:
    """ロック中ならHTTPException(429)を送出。"""
    if user.locked_until and user.locked_until > datetime.utcnow():
        remaining = max(1, int((user.locked_until - datetime.utcnow()).total_seconds() / 60) + 1)
        raise HTTPException(
            status_code=429,
            detail=f"アカウントがロックされています。約{remaining}分後に再試行してください。",
        )


def _on_login_failure(user: User, db: Session, ip: Optional[str], reason: str) -> None:
    from backend.utils.access_log import log_access
    user.failed_attempts = (user.failed_attempts or 0) + 1
    if user.failed_attempts >= _MAX_FAILED_ATTEMPTS:
        user.locked_until = datetime.utcnow() + timedelta(minutes=_LOCKOUT_MINUTES)
        db.commit()
        log_access(db, "account_locked", user_id=user.id, ip_addr=ip,
                   details={"reason": reason, "attempts": user.failed_attempts})
        raise HTTPException(
            status_code=429,
            detail=f"ログイン失敗が{_MAX_FAILED_ATTEMPTS}回に達しました。{_LOCKOUT_MINUTES}分間ロックされます。",
        )
    db.commit()
    log_access(db, "login_failed", user_id=user.id, ip_addr=ip, details={"reason": reason})
    raise HTTPException(status_code=401, detail="login failed")


def _on_login_success(user: User, db: Session) -> None:
    if user.failed_attempts:
        user.failed_attempts = 0
        user.locked_until = None
        db.commit()


# ── ページアクセス ────────────────────────────────────────────────────────────

def _get_page_access(user_id: int, user: User, db: Session) -> list[str]:
    individual = (
        db.query(PlayerPageAccess.page_key)
        .filter(PlayerPageAccess.user_id == user_id)
        .all()
    )
    team_grants: list = []
    if user and user.team_name:
        team_grants = (
            db.query(PlayerPageAccess.page_key)
            .filter(
                PlayerPageAccess.team_name == user.team_name,
                PlayerPageAccess.user_id.is_(None),
            )
            .all()
        )
    return list({row[0] for row in individual + team_grants})


from backend.utils.access_log import log_access
from backend.utils.jwt_utils import create_access_token

# ── Pydantic スキーマ ─────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    grant_type: str
    username: Optional[str] = None
    identifier: Optional[str] = None
    password: Optional[str] = None
    user_id: Optional[int] = None
    pin: Optional[str] = None
    role: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str = ""
    token_type: str = "bearer"
    role: str = ""
    user_id: int = 0
    player_id: Optional[int] = None
    team_name: Optional[str] = None
    display_name: Optional[str] = None
    mfa_required: bool = False
    mfa_token: Optional[str] = None


class BootstrapStatusResponse(BaseModel):
    has_admin: bool
    bootstrap_configured: bool
    # bootstrap_username / bootstrap_display_name は除外済み
    # 管理者ユーザー名を無認証で公開するとブルートフォースの標的になるため


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaCodeRequest(BaseModel):
    code: str


class MfaLoginRequest(BaseModel):
    mfa_token: str
    code: str


# ── ブートストラップ ─────────────────────────────────────────────────────────

def _bootstrap_admin_status(db: Session) -> BootstrapStatusResponse:
    exists = db.query(User).filter(User.role == "admin").first()
    configured = bool((settings.BOOTSTRAP_ADMIN_PASSWORD or "").strip())
    return BootstrapStatusResponse(
        has_admin=exists is not None,
        bootstrap_configured=configured,
    )


def _seed_admin_if_needed(db: Session) -> None:
    status = _bootstrap_admin_status(db)
    if status.has_admin:
        return

    password = (settings.BOOTSTRAP_ADMIN_PASSWORD or "").strip()
    if not password:
        logger.warning(
            "No admin user exists and BOOTSTRAP_ADMIN_PASSWORD is not set. "
            "Set BOOTSTRAP_ADMIN_PASSWORD before first admin login."
        )
        return

    bootstrap_username = (settings.BOOTSTRAP_ADMIN_USERNAME or "admin001").strip() or "admin001"
    bootstrap_display_name = (settings.BOOTSTRAP_ADMIN_DISPLAY_NAME or "Admin").strip() or "Admin"

    conflicting_user = db.query(User).filter(User.username == bootstrap_username).first()
    if conflicting_user:
        logger.warning(
            "Cannot bootstrap initial admin user '%s' because that username already belongs to role '%s'.",
            bootstrap_username,
            conflicting_user.role,
        )
        return

    admin = User(
        username=bootstrap_username,
        role="admin",
        display_name=bootstrap_display_name,
        hashed_credential=_hash_password(password),
    )
    db.add(admin)
    db.commit()
    logger.warning(
        "Bootstrapped initial admin user '%s'. Change the password after first login.",
        bootstrap_username,
    )


# ── ログイン ──────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = _get_ip(request)
    from backend.utils.control_plane import allow_seed_admin, allow_select_login
    if allow_seed_admin(request):
        _seed_admin_if_needed(db)

    if req.grant_type == "credential":
        identifier = (req.identifier or req.username or "").strip()
        secret = req.password if req.password is not None else req.pin
        if not identifier or not secret:
            raise HTTPException(status_code=422, detail="identifier and password are required")

        user = db.query(User).filter(User.username == identifier).first()

        if not user or not user.hashed_credential:
            # ユーザー不在時もダミーbcryptを実行してタイミング差を消す
            _verify_password(secret, "$2b$12$dummyhashfortimingequalizationxxxxxxxxxxxxxxxx")
            log_access(db, "login_failed", details={"reason": "user_not_found", "identifier": identifier}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="login failed")

        _check_lockout(user)

        if not _verify_password(secret, user.hashed_credential):
            _on_login_failure(user, db, ip, "wrong_password")

        _on_login_success(user, db)

        # MFA 有効ならプリ認証トークンを返す
        if user.totp_enabled:
            mfa_token = create_access_token(user.id, "mfa_pending", hours=5 / 60)
            log_access(db, "login_mfa_required", user_id=user.id, ip_addr=ip)
            return LoginResponse(mfa_required=True, mfa_token=mfa_token)

        token = create_access_token(user.id, user.role, user.player_id, team_name=user.team_name)
        log_access(db, "login", user_id=user.id, ip_addr=ip)
        return LoginResponse(
            access_token=token,
            role=user.role,
            user_id=user.id,
            player_id=user.player_id,
            team_name=user.team_name,
            display_name=user.display_name or user.username,
        )

    if req.grant_type == "password":
        if not req.username or not req.password:
            raise HTTPException(status_code=422, detail="username and password are required")
        user = db.query(User).filter(User.username == req.username).first()
        if not user or not user.hashed_credential:
            _verify_password(req.password, "$2b$12$dummyhashfortimingequalizationxxxxxxxxxxxxxxxx")
            log_access(db, "login_failed", details={"reason": "user_not_found", "username": req.username}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="login failed")
        _check_lockout(user)
        if not _verify_password(req.password, user.hashed_credential):
            _on_login_failure(user, db, ip, "wrong_password")
        _on_login_success(user, db)
        token = create_access_token(user.id, user.role, user.player_id)
        log_access(db, "login", user_id=user.id, ip_addr=ip)
        return LoginResponse(
            access_token=token,
            role=user.role,
            user_id=user.id,
            player_id=user.player_id,
            team_name=user.team_name,
            display_name=user.display_name or user.username,
        )

    if req.grant_type == "select":
        if not allow_select_login(request):
            raise HTTPException(status_code=403, detail="select login はローカルからのみ利用できます")
        allowed = {"analyst", "coach"}
        role = req.role
        if role not in allowed:
            raise HTTPException(status_code=422, detail=f"select grant supports only {sorted(allowed)}")
        if req.user_id:
            user = db.get(User, req.user_id)
            allowed_roles = {role, "admin"} if role == "analyst" else {role}
            if not user or user.role not in allowed_roles:
                raise HTTPException(status_code=404, detail="user not found")
        else:
            user = db.query(User).filter(User.role == role).first()
            if not user:
                token = create_access_token(0, role)
                log_access(db, "login", details={"role": role, "method": "select"}, ip_addr=ip)
                return LoginResponse(access_token=token, role=role, user_id=0)
        token = create_access_token(user.id, user.role, user.player_id, team_name=user.team_name)
        log_access(db, "login", user_id=user.id, ip_addr=ip)
        return LoginResponse(
            access_token=token,
            role=user.role,
            user_id=user.id,
            player_id=user.player_id,
            team_name=user.team_name,
            display_name=user.display_name or user.username,
        )

    if req.grant_type == "pin":
        if not req.user_id:
            raise HTTPException(status_code=422, detail="user_id is required")
        user = db.get(User, req.user_id)
        if not user or user.role != "player":
            log_access(db, "login_failed", details={"reason": "user_not_found", "user_id": req.user_id}, ip_addr=ip)
            raise HTTPException(status_code=401, detail="login failed")
        _check_lockout(user)
        if user.hashed_credential and not _verify_password(req.pin or "", user.hashed_credential):
            _on_login_failure(user, db, ip, "wrong_pin")
        _on_login_success(user, db)
        token = create_access_token(user.id, user.role, user.player_id)
        log_access(db, "login", user_id=user.id, ip_addr=ip)
        return LoginResponse(
            access_token=token,
            role=user.role,
            user_id=user.id,
            player_id=user.player_id,
            team_name=user.team_name,
            display_name=user.display_name or user.username,
        )

    raise HTTPException(status_code=422, detail=f"unsupported grant_type: {req.grant_type}")


# ── MFA ログイン（プリ認証トークン → フルJWT） ──────────────────────────────

@router.post("/mfa/login", response_model=LoginResponse)
def mfa_login(req: MfaLoginRequest, request: Request, db: Session = Depends(get_db)):
    """credential ログイン後、MFAコードを検証してフルJWTを発行する。"""
    from backend.utils.jwt_utils import verify_token
    ip = _get_ip(request)
    payload = verify_token(req.mfa_token)
    if not payload or payload.get("role") != "mfa_pending":
        raise HTTPException(status_code=401, detail="MFAトークンが無効または期限切れです")
    user_id = int(payload.get("sub", 0))
    user = db.get(User, user_id)
    if not user or not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=401, detail="MFAが有効化されていません")
    if not _verify_totp(user.totp_secret, req.code):
        raise HTTPException(status_code=401, detail="認証コードが無効です")
    token = create_access_token(user.id, user.role, user.player_id, team_name=user.team_name)
    log_access(db, "login_mfa_ok", user_id=user.id, ip_addr=ip)
    return LoginResponse(
        access_token=token,
        role=user.role,
        user_id=user.id,
        player_id=user.player_id,
        team_name=user.team_name,
        display_name=user.display_name or user.username,
    )


# ── MFA セットアップ ─────────────────────────────────────────────────────────

@router.post("/mfa/setup", response_model=MfaSetupResponse)
def mfa_setup(request: Request, db: Session = Depends(get_db)):
    """TOTPシークレットを生成してユーザーに返す（まだ有効化しない）。"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")
    user = db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    secret = _totp_generate_secret()
    user.totp_secret = secret
    db.commit()
    return MfaSetupResponse(secret=secret, otpauth_uri=_totp_uri(secret, user.username))


@router.post("/mfa/confirm")
def mfa_confirm(req: MfaCodeRequest, request: Request, db: Session = Depends(get_db)):
    """TOTPコードを検証してMFAを有効化する。"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")
    user = db.get(User, ctx.user_id)
    if not user or not user.totp_secret:
        raise HTTPException(status_code=400, detail="MFAセットアップが未完了です（/mfa/setup を先に呼んでください）")
    if not _verify_totp(user.totp_secret, req.code):
        raise HTTPException(status_code=400, detail="認証コードが無効です")
    user.totp_enabled = True
    db.commit()
    log_access(db, "mfa_enabled", user_id=user.id)
    return {"success": True, "message": "MFAが有効化されました"}


@router.post("/mfa/disable")
def mfa_disable(req: MfaCodeRequest, request: Request, db: Session = Depends(get_db)):
    """TOTPコードを確認してMFAを無効化する。"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")
    user = db.get(User, ctx.user_id)
    if not user or not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="MFAは有効化されていません")
    if not _verify_totp(user.totp_secret, req.code):
        raise HTTPException(status_code=400, detail="認証コードが無効です")
    user.totp_secret = None
    user.totp_enabled = False
    db.commit()
    log_access(db, "mfa_disabled", user_id=user.id)
    return {"success": True, "message": "MFAが無効化されました"}


@router.get("/mfa/status")
def mfa_status(request: Request, db: Session = Depends(get_db)):
    """自分のMFA有効化状態を確認する。"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")
    user = db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    return {"success": True, "mfa_enabled": bool(user.totp_enabled)}


# ── ブートストラップステータス ───────────────────────────────────────────────

@router.get("/bootstrap-status", response_model=BootstrapStatusResponse)
def bootstrap_status(db: Session = Depends(get_db)):
    """Expose initial-admin bootstrap readiness without revealing secrets."""
    return _bootstrap_admin_status(db)


# ── ログアウト（JWTブラックリスト登録） ──────────────────────────────────────

@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    from backend.utils.auth import get_auth
    from backend.utils.jwt_utils import revoke_token

    ctx = get_auth(request)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        from jose import jwt as _jose_jwt, JWTError
        try:
            payload = _jose_jwt.decode(
                auth_header[7:], settings.SECRET_KEY, algorithms=["HS256"]
            )
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                expires_at = datetime.utcfromtimestamp(exp)
                revoke_token(jti, getattr(ctx, "user_id", None), expires_at)
        except JWTError:
            pass

    log_access(db, "logout", user_id=getattr(ctx, "user_id", None))
    return {"success": True}


# ── /me ──────────────────────────────────────────────────────────────────────

@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    from backend.utils.auth import get_auth

    ctx = get_auth(request)
    if not ctx.role:
        raise HTTPException(status_code=401, detail="not logged in")
    user_id = getattr(ctx, "user_id", None)
    user = db.get(User, user_id) if user_id else None

    if ctx.role == "player" and user_id and user:
        page_access = _get_page_access(user_id, user, db)
    else:
        page_access = list(GRANTABLE_PAGES)

    return {
        "role": ctx.role,
        "player_id": ctx.player_id,
        "user_id": user_id,
        "team_name": ctx.team_name,
        "display_name": (user.display_name or user.username) if user else None,
        "page_access": page_access,
        "mfa_enabled": bool(user.totp_enabled) if user else False,
    }


# ── 選手・コーチ・アナリスト一覧（要認証） ───────────────────────────────────

@router.get("/players")
def list_players_for_login(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.role == "player").all()
    result = []
    for user in users:
        player = db.get(Player, user.player_id) if user.player_id else None
        result.append(
            {
                "user_id": user.id,
                "player_id": user.player_id,
                "display_name": user.display_name or (player.name if player else user.username),
                "has_pin": user.hashed_credential is not None,
            }
        )
    return {"success": True, "data": result}


@router.get("/coaches")
def list_coaches_for_login(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.role == "coach").all()
    return {
        "success": True,
        "data": [{"user_id": user.id, "display_name": user.display_name or user.username} for user in users],
    }


@router.get("/analysts")
def list_analysts_for_login(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.role.in_(["analyst", "admin"])).all()
    return {
        "success": True,
        "data": [
            {"user_id": user.id, "display_name": user.display_name or user.username, "role": user.role}
            for user in users
        ],
    }


# ── ユーザー管理 (admin / analyst) ───────────────────────────────────────────

def _require_admin(request: Request) -> None:
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin role required")


class UserCreate(BaseModel):
    role: str
    display_name: str
    username: str
    password: Optional[str] = None
    pin: Optional[str] = None
    player_id: Optional[int] = None
    team_name: Optional[str] = None


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    pin: Optional[str] = None
    team_name: Optional[str] = None
    player_id: Optional[int] = None


def _user_to_dict(user: User, db: Session) -> dict:
    player = db.get(Player, user.player_id) if user.player_id else None
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
        "team_name": user.team_name,
        "player_id": user.player_id,
        "player_name": player.name if player else None,
        "has_credential": user.hashed_credential is not None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "mfa_enabled": bool(user.totp_enabled),
        "locked": bool(user.locked_until and user.locked_until > datetime.utcnow()),
    }


@router.get("/users")
def list_users(request: Request, db: Session = Depends(get_db)):
    from backend.utils.auth import get_auth
    ctx = get_auth(request)

    if ctx.is_admin or ctx.is_analyst:
        users = db.query(User).order_by(User.id).all()
        return {"success": True, "data": [_user_to_dict(u, db) for u in users]}

    if ctx.is_coach:
        team = (ctx.team_name or "").strip()
        if not team:
            return {"success": True, "data": []}
        users = db.query(User).filter(User.team_name == team).order_by(User.id).all()
        return {"success": True, "data": [_user_to_dict(u, db) for u in users]}

    if ctx.is_player and ctx.user_id:
        user = db.get(User, ctx.user_id)
        return {"success": True, "data": [_user_to_dict(user, db)] if user else []}

    raise HTTPException(status_code=403, detail="ユーザー一覧の権限がありません")


@router.post("/users", status_code=201)
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db)):
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not (ctx.is_admin or ctx.is_analyst):
        raise HTTPException(status_code=403, detail="ユーザー作成は admin / analyst のみ可能です")
    allowed_roles = {"admin", "analyst", "coach", "player"}
    if body.role not in allowed_roles:
        raise HTTPException(status_code=422, detail=f"invalid role: {body.role}")
    login_id = _validate_login_id(body.username)
    existing = db.query(User).filter(User.username == login_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="login_id is already in use")

    password = (body.password or "").strip()
    if password:
        _validate_password_strength(password)

    hashed = _hash_user_credential(body.password, body.pin)
    user = User(
        username=login_id,
        role=body.role,
        display_name=body.display_name,
        team_name=body.team_name,
        player_id=body.player_id,
        hashed_credential=hashed,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_access(db, "user_created", user_id=user.id, details={"role": body.role, "display_name": body.display_name})
    return {"success": True, "data": {"id": user.id, "role": user.role, "display_name": user.display_name}}


@router.put("/users/{target_id}")
def update_user(target_id: int, body: UserUpdate, request: Request, db: Session = Depends(get_db)):
    from backend.utils.auth import get_auth
    ctx = get_auth(request)

    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")

    if ctx.is_admin or ctx.is_analyst:
        pass
    elif ctx.is_coach:
        team = (ctx.team_name or "").strip()
        if not team or (user.team_name or "").strip() != team:
            raise HTTPException(status_code=403, detail="自チームのユーザーのみ編集できます")
    elif ctx.is_player:
        if ctx.user_id != target_id:
            raise HTTPException(status_code=403, detail="自分自身のみ編集できます")
        body = UserUpdate(display_name=body.display_name, password=body.password, pin=body.pin)
    else:
        raise HTTPException(status_code=403, detail="編集権限がありません")

    if body.display_name is not None:
        user.display_name = body.display_name
    if body.username is not None and (ctx.is_admin or ctx.is_analyst):
        login_id = _validate_login_id(body.username)
        existing = db.query(User).filter(User.username == login_id, User.id != target_id).first()
        if existing:
            raise HTTPException(status_code=409, detail="login_id is already in use")
        user.username = login_id
    if body.team_name is not None and (ctx.is_admin or ctx.is_analyst or ctx.is_coach):
        user.team_name = body.team_name
    if body.player_id is not None and (ctx.is_admin or ctx.is_analyst):
        user.player_id = body.player_id

    password = (body.password or "").strip()
    if password:
        _validate_password_strength(password)

    hashed = _hash_user_credential(body.password, body.pin)
    if hashed:
        user.hashed_credential = hashed
    db.commit()
    log_access(db, "user_updated", user_id=user.id)
    return {"success": True}


@router.post("/users/{target_id}/unlock")
def unlock_user(target_id: int, request: Request, db: Session = Depends(get_db)):
    """管理者がアカウントロックを手動解除する。"""
    _require_admin(request)
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
    log_access(db, "account_unlocked", details={"target_user_id": target_id})
    return {"success": True}


@router.delete("/users/{target_id}")
def delete_user(target_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if ctx.user_id == target_id:
        raise HTTPException(status_code=400, detail="cannot delete your own user")
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    db.delete(user)
    db.commit()
    log_access(db, "user_deleted", details={"deleted_user_id": target_id})
    return {"success": True}


# ── ページアクセス付与管理 ───────────────────────────────────────────────────

class PageAccessBody(BaseModel):
    page_keys: list[str]


def _require_manager(request: Request) -> None:
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not (ctx.is_admin or ctx.is_analyst or ctx.is_coach):
        raise HTTPException(status_code=403, detail="管理者・アナリスト・コーチのみ操作できます")


@router.get("/users/{target_id}/page-access")
def get_user_page_access(target_id: int, request: Request, db: Session = Depends(get_db)):
    _require_manager(request)
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    rows = db.query(PlayerPageAccess).filter(PlayerPageAccess.user_id == target_id).all()
    return {"success": True, "data": [r.page_key for r in rows]}


@router.put("/users/{target_id}/page-access")
def set_user_page_access(target_id: int, body: PageAccessBody, request: Request, db: Session = Depends(get_db)):
    from backend.utils.auth import get_auth
    _require_manager(request)
    ctx = get_auth(request)
    user = db.get(User, target_id)
    if not user or user.role != "player":
        raise HTTPException(status_code=404, detail="player user not found")
    valid = {k for k in body.page_keys if k in GRANTABLE_PAGES}
    db.query(PlayerPageAccess).filter(
        PlayerPageAccess.user_id == target_id,
        PlayerPageAccess.team_name.is_(None),
    ).delete()
    for key in valid:
        db.add(PlayerPageAccess(page_key=key, user_id=target_id, granted_by_user_id=ctx.user_id))
    db.commit()
    return {"success": True, "data": list(valid)}


@router.get("/teams/{team_name}/page-access")
def get_team_page_access(team_name: str, request: Request, db: Session = Depends(get_db)):
    _require_manager(request)
    rows = (
        db.query(PlayerPageAccess)
        .filter(PlayerPageAccess.team_name == team_name, PlayerPageAccess.user_id.is_(None))
        .all()
    )
    return {"success": True, "data": [r.page_key for r in rows]}


@router.put("/teams/{team_name}/page-access")
def set_team_page_access(team_name: str, body: PageAccessBody, request: Request, db: Session = Depends(get_db)):
    from backend.utils.auth import get_auth
    _require_manager(request)
    ctx = get_auth(request)
    valid = {k for k in body.page_keys if k in GRANTABLE_PAGES}
    db.query(PlayerPageAccess).filter(
        PlayerPageAccess.team_name == team_name,
        PlayerPageAccess.user_id.is_(None),
    ).delete()
    for key in valid:
        db.add(PlayerPageAccess(page_key=key, team_name=team_name, granted_by_user_id=ctx.user_id))
    db.commit()
    return {"success": True, "data": list(valid)}
