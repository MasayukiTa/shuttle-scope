"""Authentication and user-management routes."""

import base64
import hashlib
import hmac as _hmac_mod
import logging
import os
import re as _re
import struct
import threading
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

import bcrypt as _bcrypt_lib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db.models import Player, PlayerPageAccess, User

GRANTABLE_PAGES = {"prediction", "expert_labeler"}

_MAX_FAILED_ATTEMPTS = 3
_LOCKOUT_MINUTES = 30
_PASSWORD_MIN_LENGTH = 12
# bcrypt は入力 password を 72 byte で silent truncate する (CVE-class CWE-521)。
# `pw[:72] + X` と `pw[:72] + Y` が同じハッシュにマッチしてしまうため、
# 部分漏洩した password でログインできる経路を塞ぐ目的で 72 byte を上限とする。
# 文字数ではなく UTF-8 バイト数で制限する点に注意 (日本語は 1 文字 3 byte)。
_PASSWORD_MAX_BYTES = 72

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# タイミング均一化用ダミーハッシュ（起動時1回だけ生成、有効な bcrypt ハッシュ形式）
_DUMMY_BCRYPT_HASH: str = _bcrypt_lib.hashpw(b"_dummy_timing_eq_", _bcrypt_lib.gensalt(rounds=12)).decode()

# IP ベースのログインレート制限（標準ライブラリのみ）
_IP_RATE_LOCK    = threading.Lock()
_IP_LOGIN_TIMES: dict[str, list[float]] = defaultdict(list)
_IP_RATE_WINDOW  = 60   # 秒
_IP_RATE_LIMIT   = 10   # 同一 IP から 60 秒以内に 10 回まで


def _check_ip_rate_limit(ip: Optional[str]) -> None:
    if not ip:
        return
    now = time.time()
    cutoff = now - _IP_RATE_WINDOW
    with _IP_RATE_LOCK:
        times = [t for t in _IP_LOGIN_TIMES[ip] if t > cutoff]
        _IP_LOGIN_TIMES[ip] = times
        if len(times) >= _IP_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"リクエストが多すぎます。{_IP_RATE_WINDOW}秒後に再試行してください。",
            )
        _IP_LOGIN_TIMES[ip].append(now)

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
    # bcrypt 72-byte truncation 対策。文字数ではなく UTF-8 バイト数で計測する。
    if len(password.encode("utf-8")) > _PASSWORD_MAX_BYTES:
        raise HTTPException(
            422,
            f"パスワードは {_PASSWORD_MAX_BYTES} バイト以下にしてください "
            f"(英数記号 {_PASSWORD_MAX_BYTES} 文字 / 日本語 ~24 文字)",
        )
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
    # CF-Connecting-IP は Cloudflare 側で設定される（偽造不可）。
    # X-Forwarded-For はクライアントが任意に設定できるためログイン
    # IP レート制限の根拠に使ってはならない（レート制限バイパス防止）。
    cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
    if cf_ip:
        return cf_ip
    return request.client.host if request.client else None


# ── アカウントロックアウト ────────────────────────────────────────────────────

def _check_lockout(user: User) -> None:
    """ロック中ならHTTPException(429)を送出。
    ロック期間が経過していたら failed_attempts を 0 に戻し、解除直後の 1 回失敗で
    再ロックされる挙動を防ぐ (新規 _MAX_FAILED_ATTEMPTS=3 回まで失敗を許容する)。
    """
    if user.locked_until and user.locked_until > datetime.utcnow():
        remaining = max(1, int((user.locked_until - datetime.utcnow()).total_seconds() / 60) + 1)
        raise HTTPException(
            status_code=429,
            detail=f"アカウントがロックされています。約{remaining}分後に再試行してください。",
        )
    # ロック期間が経過 (locked_until が past or None) で failed_attempts が残っているなら
    # カウンタをリセットしてフレッシュな失敗回数枠を与える。これがないと、3 → 1 で
    # すぐ再ロックされる UX 上の問題を生む。SQLAlchemy session に attached なら
    # 後続の commit で永続化されるが、明示 commit はしない (呼び出し元の login flow
    # が _on_login_success/failure で commit するため)。
    if (user.failed_attempts or 0) > 0 and (
        user.locked_until is None or user.locked_until <= datetime.utcnow()
    ):
        user.failed_attempts = 0
        user.locked_until = None


def _timing_padding_db_write(db: Session) -> None:
    """user_not_found 経路でも存在ユーザ経路と同等の DB write コストを発生させる。

    存在ユーザ失敗時の _on_login_failure は users テーブルへの UPDATE + commit を
    追加で実施するため、未存在ユーザより ~30ms 早く応答してしまい、
    タイミング側チャネルでユーザ名列挙が可能になる (CWE-204)。
    ここで 0 行にマッチする UPDATE + commit を実行して時間を揃える。
    """
    from sqlalchemy import text
    try:
        db.execute(text("UPDATE users SET failed_attempts = failed_attempts WHERE id = -1"))
        db.commit()
    except Exception:
        # いかなる理由でも失敗しても認証側の挙動を変えない
        try:
            db.rollback()
        except Exception:
            pass


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
from backend.utils.jwt_utils import (
    create_access_token,
    create_refresh_token,
    persist_refresh_token,
    rotate_refresh_token,
    revoke_refresh_token_by_plain,
    revoke_all_refresh_tokens_for_user,
)

# ── Pydantic スキーマ ─────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    # 任意フィールドの混入を遮断 (mass assignment / 監査ログ汚染対策)。
    # 各フィールドの max_length は audit_logs.details に巨大文字列が
    # 蓄積される storage DoS を防ぐためのもの。
    model_config = {"extra": "forbid"}

    grant_type: str = Field(..., max_length=32)
    username: Optional[str] = Field(default=None, max_length=64)
    identifier: Optional[str] = Field(default=None, max_length=64)
    password: Optional[str] = Field(default=None, max_length=256)
    user_id: Optional[int] = None
    pin: Optional[str] = Field(default=None, max_length=128)
    role: Optional[str] = Field(default=None, max_length=32)


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
    refresh_token: Optional[str] = None


class RefreshRequest(BaseModel):
    model_config = {"extra": "forbid"}
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def _issue_refresh_for(user_id: int) -> Optional[str]:
    """user_id 用の refresh token を発行して DB に hash 保存し、平文を返す。
    user_id=0（ロール無し select ログイン）は対象外。"""
    if not user_id:
        return None
    try:
        raw, jti, exp = create_refresh_token(user_id)
        persist_refresh_token(user_id, raw, jti, exp)
        return raw
    except Exception:
        return None


class BootstrapStatusResponse(BaseModel):
    has_admin: bool
    bootstrap_configured: bool
    # bootstrap_username / bootstrap_display_name は除外済み
    # 管理者ユーザー名を無認証で公開するとブルートフォースの標的になるため


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaCodeRequest(BaseModel):
    model_config = {"extra": "forbid"}
    # TOTP は 6 桁数字。緩めの 16 文字までで上限を切って巨大値による
    # 文字列処理コスト攻撃を遮断する。
    code: str = Field(..., max_length=16)


class MfaLoginRequest(BaseModel):
    model_config = {"extra": "forbid"}
    # 短命 JWT (mfa_pending) を想定。署名込み JWT は 200〜400 byte 程度なので
    # 1024 で十分。code は 6 桁数字。
    mfa_token: str = Field(..., max_length=1024)
    code: str = Field(..., max_length=16)


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
    _check_ip_rate_limit(ip)
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
            _verify_password(secret, _DUMMY_BCRYPT_HASH)
            log_access(db, "login_failed", details={"reason": "user_not_found", "identifier": identifier}, ip_addr=ip)
            # 存在ユーザ経路の _on_login_failure の UPDATE+commit と等価のダミー書き込み
            _timing_padding_db_write(db)
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
            refresh_token=_issue_refresh_for(user.id),
        )

    if req.grant_type == "password":
        if not req.username or not req.password:
            raise HTTPException(status_code=422, detail="username and password are required")
        user = db.query(User).filter(User.username == req.username).first()
        if not user or not user.hashed_credential:
            _verify_password(req.password, _DUMMY_BCRYPT_HASH)
            log_access(db, "login_failed", details={"reason": "user_not_found", "username": req.username}, ip_addr=ip)
            _timing_padding_db_write(db)
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
            refresh_token=_issue_refresh_for(user.id),
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
            # Z1 fix: select grant では「指定 role」と完全一致するユーザのみ許可。
            # 以前は role=analyst リクエストが admin user とも一致してしまい、
            # パスワード/lockout 不要で admin JWT を発行する経路があった (privilege escalation)。
            if not user or user.role != role:
                raise HTTPException(status_code=404, detail="user not found")
            # Z2 fix: select 経路でも lockout を尊重する。
            # ローカル限定でも lockout 機構を完全無効化する経路は disable する。
            _check_lockout(user)
        else:
            user = db.query(User).filter(User.role == role).first()
            if not user:
                token = create_access_token(0, role)
                log_access(db, "login", details={"role": role, "method": "select"}, ip_addr=ip)
                return LoginResponse(access_token=token, role=role, user_id=0)
            # ユーザを暗黙選択した場合も lockout を尊重する
            _check_lockout(user)
        token = create_access_token(user.id, user.role, user.player_id, team_name=user.team_name)
        log_access(db, "login", user_id=user.id, ip_addr=ip)
        return LoginResponse(
            access_token=token,
            role=user.role,
            user_id=user.id,
            player_id=user.player_id,
            team_name=user.team_name,
            display_name=user.display_name or user.username,
            refresh_token=_issue_refresh_for(user.id),
        )

    if req.grant_type == "pin":
        if not req.user_id:
            raise HTTPException(status_code=422, detail="user_id is required")
        user = db.get(User, req.user_id)
        if not user or user.role != "player":
            # 不存在 or 非playerロール時もダミーbcryptを実行してタイミング差を消す
            _verify_password(req.pin or "", _DUMMY_BCRYPT_HASH)
            log_access(db, "login_failed", details={"reason": "user_not_found", "user_id": req.user_id}, ip_addr=ip)
            _timing_padding_db_write(db)
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
            refresh_token=_issue_refresh_for(user.id),
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
    # MFA brute force 防御 (10 分 10 回上限) — mfa_confirm と共通カウンタ
    _check_mfa_brute_limit(user_id)
    user = db.get(User, user_id)
    if not user or not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=401, detail="MFAが有効化されていません")
    # Z3 fix: lockout 中のユーザに対して MFA 経路で JWT を発行しない。
    # mfa_token は credential 経路の pre-auth で発行されるが、その後 lockout が
    # 確定した場合 (パスワード正解直後にロック等) に MFA 経路で素通りされる懸念を遮断。
    _check_lockout(user)
    if not _verify_totp(user.totp_secret, req.code):
        _record_mfa_failure(user_id)
        raise HTTPException(status_code=401, detail="認証コードが無効です")
    token = create_access_token(user.id, user.role, user.player_id, team_name=user.team_name)
    log_access(db, "login_mfa_ok", user_id=user.id, ip_addr=ip)
    return LoginResponse(
        access_token=token,
        refresh_token=_issue_refresh_for(user.id),
        role=user.role,
        user_id=user.id,
        player_id=user.player_id,
        team_name=user.team_name,
        display_name=user.display_name or user.username,
    )


# ── MFA セットアップ ─────────────────────────────────────────────────────────

# MFA setup 連投による DB write amplification / secret rotation 乱用を防ぐための rate limit
# 1 user あたり 10 分間に最大 5 回まで
import threading as _th_setup
import time as _t_setup
_mfa_setup_counters: dict[int, list[float]] = {}
_mfa_setup_lock = _th_setup.Lock()
_MFA_SETUP_WINDOW_SEC = 600
_MFA_SETUP_MAX = 5


@router.post("/mfa/setup", response_model=MfaSetupResponse)
def mfa_setup(request: Request, db: Session = Depends(get_db)):
    """TOTPシークレットを生成してユーザーに返す（まだ有効化しない）。"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")
    # Per-user rate limit (DB write amplification 防御)
    now = _t_setup.time()
    with _mfa_setup_lock:
        arr = _mfa_setup_counters.get(ctx.user_id, [])
        cutoff = now - _MFA_SETUP_WINDOW_SEC
        arr = [t for t in arr if t >= cutoff]
        _mfa_setup_counters[ctx.user_id] = arr
        if len(arr) >= _MFA_SETUP_MAX:
            raise HTTPException(
                status_code=429,
                detail=f"MFA セットアップ試行が多すぎます。{_MFA_SETUP_WINDOW_SEC // 60} 分後に再試行してください。",
            )
        arr.append(now)
    user = db.get(User, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    # 既に MFA 有効なユーザに対する setup は拒否する。
    # (トークン奪取者が secret を再生成して正規ユーザをロックアウトする攻撃経路を遮断)
    # MFA を再生成したい場合は /mfa/disable で既存コード検証後に改めて setup すること。
    if getattr(user, "totp_enabled", False):
        raise HTTPException(
            status_code=409,
            detail="MFA は既に有効です。再設定する場合は /mfa/disable で無効化後にセットアップしてください。",
        )
    secret = _totp_generate_secret()
    user.totp_secret = secret
    db.commit()
    return MfaSetupResponse(secret=secret, otpauth_uri=_totp_uri(secret, user.username))


# MFA confirm/login brute force 防御: user_id ごとに失敗カウントをメモリ保持
# 10 分窓で 10 回連続失敗で 15 分ロック (6 桁 = 10^6 だが 10/分で 10万分 ≒ 約 70 日必要)
import threading as _th_mfa
import time as _t_mfa
_mfa_failures: dict[int, list[float]] = {}
_mfa_lock = _th_mfa.Lock()
_MFA_WINDOW_SEC = 600
_MFA_MAX_FAILURES = 10


def _check_mfa_brute_limit(user_id: int) -> None:
    """MFA コード推測に対する rate limit。"""
    if not user_id:
        return
    now = _t_mfa.time()
    with _mfa_lock:
        arr = _mfa_failures.get(user_id, [])
        cutoff = now - _MFA_WINDOW_SEC
        arr = [t for t in arr if t >= cutoff]
        _mfa_failures[user_id] = arr
        if len(arr) >= _MFA_MAX_FAILURES:
            raise HTTPException(
                status_code=429,
                detail=f"MFA 失敗が多すぎます。{_MFA_WINDOW_SEC // 60} 分後に再試行してください。",
            )


def _record_mfa_failure(user_id: int) -> None:
    if not user_id:
        return
    with _mfa_lock:
        _mfa_failures.setdefault(user_id, []).append(_t_mfa.time())


@router.post("/mfa/confirm")
def mfa_confirm(req: MfaCodeRequest, request: Request, db: Session = Depends(get_db)):
    """TOTPコードを検証してMFAを有効化する。"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")
    # MFA brute force 防御 (10 分 10 回上限)
    _check_mfa_brute_limit(ctx.user_id)
    user = db.get(User, ctx.user_id)
    if not user or not user.totp_secret:
        raise HTTPException(status_code=400, detail="MFAセットアップが未完了です（/mfa/setup を先に呼んでください）")
    if not _verify_totp(user.totp_secret, req.code):
        _record_mfa_failure(ctx.user_id)
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
    # MFA brute force 防御: 漏洩した access token を持つ攻撃者が 6 桁の TOTP を
    # 総当たりして MFA を無効化する経路を遮断する (mfa_confirm / mfa/login と
    # 共通のレートリミットを使用する)。
    _check_mfa_brute_limit(ctx.user_id)
    user = db.get(User, ctx.user_id)
    if not user or not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="MFAは有効化されていません")
    if not _verify_totp(user.totp_secret, req.code):
        _record_mfa_failure(ctx.user_id)
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
    status = _bootstrap_admin_status(db)
    # 初期化済みの場合は has_admin のみ返す（設定状態の詳細を隠す）
    if status.has_admin:
        return BootstrapStatusResponse(has_admin=True, bootstrap_configured=False)
    return status


# ── ログアウト（JWTブラックリスト登録） ──────────────────────────────────────

class LogoutRequest(BaseModel):
    model_config = {"extra": "forbid"}
    refresh_token: Optional[str] = None


@router.post("/logout")
def logout(
    request: Request,
    body: Optional[LogoutRequest] = None,
    db: Session = Depends(get_db),
):
    from backend.utils.auth import get_auth
    from backend.utils.jwt_utils import revoke_token

    # 先に refresh token を revoke（access token が無効でも対応できるように）
    if body and body.refresh_token:
        revoke_refresh_token_by_plain(body.refresh_token)

    auth_header = request.headers.get("Authorization", "")
    # Bearer が無い / 形式不正 → 何もせず 200 を返す（audit_logs スパム防止）
    if not auth_header.startswith("Bearer "):
        return {"success": True}

    ctx = get_auth(request)

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
        # 無効な Bearer token もログ書かず 200（スパム防止）
        return {"success": True}

    log_access(db, "logout", user_id=getattr(ctx, "user_id", None))
    return {"success": True}


# ── Refresh token による access token 再発行 ────────────────────────────────

@router.post("/refresh", response_model=RefreshResponse)
def refresh(req: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    """refresh token を rotation しつつ新しい access token を返す。

    - 使用された refresh token は即 revoke し新しい refresh を発行
    - revoke 済み refresh の再提示は reuse とみなし chain 全体を revoke
    """
    rotated = rotate_refresh_token(req.refresh_token)
    if not rotated:
        raise HTTPException(status_code=401, detail="refresh token invalid or expired")
    user = db.get(User, rotated["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="user not found")
    # Z4 fix: lockout 中のユーザに refresh 経路で新規 access token を発行しない。
    # 攻撃者が lockout 直前に refresh_token を奪取していた場合、
    # この経路で lockout を完全に無視して新規 JWT 発行できてしまう。
    _check_lockout(user)
    access = create_access_token(user.id, user.role, user.player_id, team_name=user.team_name)
    ip = _get_ip(request)
    log_access(db, "token_refresh", user_id=user.id, ip_addr=ip)
    return RefreshResponse(access_token=access, refresh_token=rotated["new_token"])


# ── パスワード変更 / 管理者リセット ───────────────────────────────────────────

class PasswordChangeRequest(BaseModel):
    # user_id / target_user_id / sub / id を body で送って他ユーザ password を変えようとする
    # IDOR 類似攻撃を 422 で明示拒否する (実際には JWT の user_id しか使わないが、
    # silent drop で 200 を返すと攻撃者に成功と誤認させる)
    model_config = {"extra": "forbid"}
    current_password: str
    new_password: str


class PasswordResetResponse(BaseModel):
    temporary_password: str


def _generate_temp_password() -> str:
    """ポリシーを満たす一時パスワードを生成 (12 文字以上、英大小/数字/記号を含む)。"""
    import secrets as _secrets
    symbols = "!@#$%^&*-_=+"
    alphabet_lower = "abcdefghijklmnopqrstuvwxyz"
    alphabet_upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    digits = "0123456789"
    # 各カテゴリから最低 1 文字ずつ
    pick = [
        _secrets.choice(alphabet_lower),
        _secrets.choice(alphabet_upper),
        _secrets.choice(digits),
        _secrets.choice(symbols),
    ]
    pool = alphabet_lower + alphabet_upper + digits + symbols
    pick += [_secrets.choice(pool) for _ in range(9)]  # 計 13 文字
    _secrets.SystemRandom().shuffle(pick)
    return "".join(pick)


@router.post("/password")
def change_password(req: PasswordChangeRequest, request: Request, db: Session = Depends(get_db)):
    """認証済みユーザが自身のパスワードを変更する。current_password の検証必須。"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.role or not ctx.user_id:
        raise HTTPException(status_code=401, detail="not logged in")

    user = db.get(User, ctx.user_id)
    if not user or not user.hashed_credential:
        raise HTTPException(status_code=404, detail="user not found")

    if not _verify_password(req.current_password, user.hashed_credential):
        ip = _get_ip(request)
        log_access(db, "password_change_failed", user_id=user.id, ip_addr=ip,
                   details={"reason": "current_password_mismatch"})
        raise HTTPException(status_code=401, detail="現在のパスワードが正しくありません")

    _validate_password_strength(req.new_password)
    user.hashed_credential = _hash_password(req.new_password)
    db.commit()
    # 既存 refresh token を全失効させ、再ログインを要求
    revoke_all_refresh_tokens_for_user(user.id)
    log_access(db, "password_changed", user_id=user.id, ip_addr=_get_ip(request))
    return {"success": True}


@router.post("/users/{target_id}/reset-password", response_model=PasswordResetResponse)
def admin_reset_password(target_id: int, request: Request, db: Session = Depends(get_db)):
    """管理者が指定ユーザの一時パスワードを発行する。ログイン後の速やかな変更が前提。"""
    _require_admin(request)
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    temp = _generate_temp_password()
    user.hashed_credential = _hash_password(temp)
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
    revoke_all_refresh_tokens_for_user(user.id)
    log_access(db, "password_reset_by_admin", details={"target_user_id": target_id})
    return PasswordResetResponse(temporary_password=temp)


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

def _allow_user_listing(request: Request) -> None:
    """ユーザ列挙系エンドポイント (/players, /coaches, /analysts) の認可。
    select login 用に設計されたため loopback では誰でも OK。Cloudflare 公開時は
    admin/analyst のみ許可する（player/coach による他ユーザ列挙を防ぐ）。"""
    from backend.utils.control_plane import is_loopback_request
    if is_loopback_request(request):
        return
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not (ctx.is_admin or ctx.is_analyst):
        raise HTTPException(status_code=403, detail="ユーザ一覧は admin/analyst のみ参照可能です")


def _scope_user_listing(request: Request, db: Session, base_query):
    """認証済み analyst/coach に対しては自チームのみ列挙する (cross-team 漏洩防止)。
    loopback (PIN ログイン画面) / admin では全件返す。"""
    from backend.utils.control_plane import is_loopback_request
    if is_loopback_request(request):
        return base_query
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if ctx.is_admin:
        return base_query
    # analyst / coach は自チームのみ
    team = (ctx.team_name or "").strip()
    if not team:
        return base_query.filter(User.id == -1)  # empty
    return base_query.filter(User.team_name == team)


@router.get("/players")
def list_players_for_login(request: Request, db: Session = Depends(get_db)):
    _allow_user_listing(request)
    users = _scope_user_listing(request, db, db.query(User).filter(User.role == "player")).all()
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
def list_coaches_for_login(request: Request, db: Session = Depends(get_db)):
    _allow_user_listing(request)
    users = _scope_user_listing(request, db, db.query(User).filter(User.role == "coach")).all()
    return {
        "success": True,
        "data": [{"user_id": user.id, "display_name": user.display_name or user.username} for user in users],
    }


@router.get("/analysts")
def list_analysts_for_login(request: Request, db: Session = Depends(get_db)):
    _allow_user_listing(request)
    # admin は全 role、analyst/coach は team scope 内の analyst のみ (admin は scope で見せない)
    users = _scope_user_listing(
        request, db, db.query(User).filter(User.role.in_(["analyst", "admin"]))
    ).all()
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


def _reject_control_chars(value: Optional[str], field_name: str, max_len: int = 200) -> Optional[str]:
    """制御文字 / BIDI override / 長大値を拒否する共通バリデータ。

    CRLF injection（ログ偽装）、null byte（バックエンド処理バグ）、
    Unicode BIDI override（UI なりすまし）、長大値（ストレージ攻撃）を防ぐ。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field_name} must be a string")
    if len(value) > max_len:
        raise HTTPException(status_code=422, detail=f"{field_name} too long (max {max_len})")
    # C0 制御文字 + LRO/RLO/PDF 等の BIDI override + ZWSP/ZWNJ/ZWJ
    DISALLOWED = set(chr(i) for i in range(32)) | {
        "​", "‌", "‍", " ", " ",
        "‪", "‫", "‬", "‭", "‮",
        "⁦", "⁧", "⁨", "⁩", "﻿",
        "",
    }
    for ch in value:
        if ch in DISALLOWED:
            raise HTTPException(
                status_code=422,
                detail=f"{field_name} contains disallowed control/format character (U+{ord(ch):04X})",
            )
    return value


class UserCreate(BaseModel):
    # mass assignment 防御: is_admin / hashed_credential / failed_attempts /
    # locked_until 等の内部フィールドを body 経由で設定させない。
    model_config = {"extra": "forbid"}

    role: str
    display_name: str
    username: str
    password: Optional[str] = None
    pin: Optional[str] = None
    player_id: Optional[int] = None
    team_name: Optional[str] = None


class UserUpdate(BaseModel):
    # 未知フィールドを silent drop せず 422 で拒否する。`is_admin` `id` 等の
    # 権限関連を body に混入させる mass assignment 攻撃を検出・遮断する。
    model_config = {"extra": "forbid"}

    display_name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    pin: Optional[str] = None
    team_name: Optional[str] = None
    player_id: Optional[int] = None
    # role は admin のみが書換可能。analyst/coach/player が role を送ってきた場合
    # 403 で明示拒否する（silent drop にするとサイレント昇格攻撃を検出困難にする）。
    role: Optional[str] = None


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

    if ctx.is_admin:
        users = db.query(User).order_by(User.id).all()
        return {"success": True, "data": [_user_to_dict(u, db) for u in users]}

    if ctx.is_analyst or ctx.is_coach:
        # analyst も自チームのみ (cross-team 情報漏洩防止)
        team = (ctx.team_name or "").strip()
        if not team:
            # loopback dev/test では admin 同等で全件返す
            from backend.utils.control_plane import allow_legacy_header_auth
            if allow_legacy_header_auth(request):
                users = db.query(User).order_by(User.id).all()
                return {"success": True, "data": [_user_to_dict(u, db) for u in users]}
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
    # role は string の完全一致のみ許可（list/空白混入/enum-bypass を遮断）
    if not isinstance(body.role, str) or body.role not in allowed_roles:
        raise HTTPException(status_code=422, detail=f"invalid role: {body.role!r}")
    # display_name / team_name の制御文字 / BIDI override を拒否
    _reject_control_chars(body.display_name, "display_name", max_len=120)
    _reject_control_chars(body.team_name, "team_name", max_len=80)
    # display_name 空文字/空白のみ拒否 + HTML タグ拒否 (stored XSS 対策)
    if not body.display_name or not body.display_name.strip():
        raise HTTPException(status_code=422, detail="display_name must not be empty or whitespace only")
    import re as _re_dn
    if _re_dn.search(r"</?(script|iframe|object|embed|svg|style|link|meta|form|img[^>]*on\w+)[\s>/]", body.display_name, _re_dn.IGNORECASE):
        raise HTTPException(status_code=422, detail="display_name contains disallowed HTML tags")
    # analyst は admin / analyst アカウントを作成できない（権限昇格防止）
    if ctx.is_analyst and body.role in ("admin", "analyst"):
        raise HTTPException(status_code=403, detail="admin/analyst アカウントは admin のみ作成できます")
    # analyst/coach/player は team_name 必須 (cross-team 漏洩防止)。
    # admin のみ team_name=None を許容（システム横断管理者として扱う）。
    if body.role != "admin":
        team = (body.team_name or "").strip()
        if not team:
            raise HTTPException(
                status_code=422,
                detail=f"team_name is required for role={body.role}",
            )
    login_id = _validate_login_id(body.username)
    existing = db.query(User).filter(User.username == login_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="login_id is already in use")
    # player_id の一意性検証 (1 player に複数 user を紐付けると なりすまし経路になる)
    if body.player_id is not None:
        if body.player_id <= 0 or body.player_id > 2**31 - 1:
            raise HTTPException(status_code=422, detail="player_id out of range")
        # 対象 player の存在 + 他 user との重複を 409 で拒否
        if not db.get(Player, body.player_id):
            raise HTTPException(status_code=422, detail=f"player_id={body.player_id} does not exist")
        dup = db.query(User).filter(User.player_id == body.player_id).first()
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"player_id={body.player_id} is already linked to user_id={dup.id}",
            )

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

    # ── role 書換は admin 限定 ────────────────────────────────────────────
    # 以下の権限昇格経路を完全遮断:
    #   - analyst が player/coach を admin に書換（ラウンド10 検出）
    #   - analyst が自分を admin に書換（自己昇格）
    #   - coach が自分や他人を analyst/admin に書換
    #   - player が自分を昇格
    if body.role is not None and not ctx.is_admin:
        raise HTTPException(
            status_code=403,
            detail="role の変更は admin のみ可能です",
        )

    # ── password 上書きは admin または自分自身のみ ─────────────────────────
    # analyst が他ユーザ (player/coach) の password を書換えてアカウント乗っ取る
    # 経路を遮断（ラウンド10 検出）。password 変更は /api/auth/password で
    # current_password 検証を通す想定。
    if body.password is not None and not ctx.is_admin and ctx.user_id != target_id:
        raise HTTPException(
            status_code=403,
            detail="他ユーザのパスワード変更は admin のみ可能です",
        )
    if body.pin is not None and not ctx.is_admin and ctx.user_id != target_id:
        raise HTTPException(
            status_code=403,
            detail="他ユーザの PIN 変更は admin のみ可能です",
        )

    # ── team_name の書換は admin のみ ────────────────────────────────────
    # analyst が player の team_name を書換えて tenant 破壊する攻撃を遮断。
    # 業務で必要なら admin に依頼する運用とする。
    if body.team_name is not None and not ctx.is_admin:
        raise HTTPException(
            status_code=403,
            detail="team_name の変更は admin のみ可能です",
        )

    # ── player_id の書換は admin のみ ────────────────────────────────────
    # analyst が自 user の player_id を他 player に書換えて「なりすまし」する経路を
    # 遮断する (player ロール以外でも player_id は PlayerAccessControlMiddleware で
    # データ可視範囲を決定する重要フィールド)。
    # 新規ユーザ作成時の player 紐付けは admin が実施する運用とする。
    if body.player_id is not None and not ctx.is_admin:
        raise HTTPException(
            status_code=403,
            detail="player_id の変更は admin のみ可能です",
        )

    if ctx.is_admin:
        pass
    elif ctx.is_analyst:
        # analyst は admin / analyst アカウントを編集できない（権限昇格・乗っ取り防止）
        if user.role in ("admin", "analyst") and ctx.user_id != target_id:
            raise HTTPException(status_code=403, detail="他の管理者/analyst を編集する権限がありません")
    elif ctx.is_coach:
        team = (ctx.team_name or "").strip()
        if not team or (user.team_name or "").strip() != team:
            raise HTTPException(status_code=403, detail="自チームのユーザーのみ編集できます")
        # coach は admin / analyst を編集できない（team_name 一致のみでの権限昇格を塞ぐ）
        if user.role in ("admin", "analyst"):
            raise HTTPException(status_code=403, detail="管理者/analyst は編集できません")
    elif ctx.is_player:
        if ctx.user_id != target_id:
            raise HTTPException(status_code=403, detail="自分自身のみ編集できます")
        # player が権限関連フィールド (username / team_name / player_id) を送ってきたら
        # silent drop ではなく 403 で明示拒否する (silent success は攻撃検出を困難にする)
        if any(v is not None for v in (body.username, body.team_name, body.player_id)):
            raise HTTPException(
                status_code=403,
                detail="player ロールは username / team_name / player_id を変更できません",
            )
        body = UserUpdate(display_name=body.display_name, password=body.password, pin=body.pin)
    else:
        raise HTTPException(status_code=403, detail="編集権限がありません")

    # display_name / team_name の制御文字 / BIDI override を拒否
    _reject_control_chars(body.display_name, "display_name", max_len=120)
    _reject_control_chars(body.team_name, "team_name", max_len=80)
    # display_name HTML タグ拒否 (stored XSS 対策、create_user と同じルール)
    if body.display_name is not None:
        if not body.display_name.strip():
            raise HTTPException(status_code=422, detail="display_name must not be empty or whitespace only")
        import re as _re_dn_upd
        if _re_dn_upd.search(
            r"</?(script|iframe|object|embed|svg|style|link|meta|form|img[^>]*on\w+)[\s>/]",
            body.display_name,
            _re_dn_upd.IGNORECASE,
        ):
            raise HTTPException(status_code=422, detail="display_name contains disallowed HTML tags")
        user.display_name = body.display_name
    if body.username is not None and (ctx.is_admin or ctx.is_analyst):
        login_id = _validate_login_id(body.username)
        existing = db.query(User).filter(User.username == login_id, User.id != target_id).first()
        if existing:
            raise HTTPException(status_code=409, detail="login_id is already in use")
        user.username = login_id
    # role は admin のみ書換可能 (上で既にガード済なのでここでは admin 限定で適用)
    if body.role is not None and ctx.is_admin:
        if body.role not in ("admin", "analyst", "coach", "player"):
            raise HTTPException(status_code=422, detail=f"invalid role: {body.role}")
        user.role = body.role
    # team_name / player_id は admin のみ書換可能 (上でガード済)
    if body.team_name is not None and ctx.is_admin:
        user.team_name = body.team_name
    if body.player_id is not None and ctx.is_admin:
        user.player_id = body.player_id

    # 最終 role が admin 以外なら team_name は必須 (空文字化を防止)
    final_role = user.role
    if final_role != "admin":
        if not (user.team_name or "").strip():
            raise HTTPException(
                status_code=422,
                detail=f"team_name is required for role={final_role}",
            )

    password = (body.password or "").strip()
    if password:
        _validate_password_strength(password)

    hashed = _hash_user_credential(body.password, body.pin)
    if hashed:
        user.hashed_credential = hashed
    db.commit()
    # 重要度の高い変更 (role/password/pin/team_name/username) は action を分けて
    # audit log に残し、検知/アラートで優先度を上げられるようにする。
    changed = body.model_dump(exclude_unset=True)
    high_risk_changed = [k for k in ("role", "password", "pin", "team_name", "username") if k in changed]
    action = "user_updated"
    if high_risk_changed:
        action = "user_updated_high_risk"
    log_access(
        db, action, user_id=ctx.user_id,
        details={
            "target_user_id": target_id,
            "fields": list(changed.keys()),
            "high_risk_fields": high_risk_changed,
            "actor_role": ctx.role,
        },
    )
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


# ── 監査ログ閲覧 (admin only) ────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    id: int
    user_id: Optional[int]
    username: Optional[str]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[int]
    details: Optional[str]
    ip_addr: Optional[str]
    created_at: str


@router.get("/audit-logs")
def list_audit_logs(
    request: Request,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    since: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """admin のみ。audit (access_logs) を新しい順に最大 limit 件返す。

    Query:
      - action: 完全一致フィルタ (例 "login_failed")
      - user_id: 該当 user_id のみ
      - since: ISO8601 datetime 以降 (created_at >= since)
      - limit: 1..500 (default 100)
    """
    from backend.db.models import AccessLog
    _require_admin(request)

    limit = max(1, min(int(limit or 100), 500))
    q = db.query(AccessLog)
    if action:
        q = q.filter(AccessLog.action == action)
    if user_id is not None:
        q = q.filter(AccessLog.user_id == user_id)
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            # naive UTC として比較
            if since_dt.tzinfo is not None:
                since_dt = since_dt.astimezone(tz=None).replace(tzinfo=None)
            q = q.filter(AccessLog.created_at >= since_dt)
        except ValueError:
            raise HTTPException(status_code=422, detail="since must be ISO8601")

    rows = q.order_by(AccessLog.created_at.desc()).limit(limit).all()

    # user_id → username を一括取得
    uids = {r.user_id for r in rows if r.user_id}
    uname_map: dict[int, str] = {}
    if uids:
        users = db.query(User).filter(User.id.in_(uids)).all()
        uname_map = {u.id: u.username for u in users}

    entries = [
        AuditLogEntry(
            id=r.id,
            user_id=r.user_id,
            username=uname_map.get(r.user_id) if r.user_id else None,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            details=r.details,
            ip_addr=r.ip_addr,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]
    return {"success": True, "data": [e.model_dump() for e in entries]}


@router.get("/audit-logs/verify")
def verify_audit_logs(request: Request, db: Session = Depends(get_db)):
    """admin のみ。access_logs のハッシュチェーンを再計算し整合性を返す。"""
    _require_admin(request)
    from backend.utils.access_log import verify_chain
    result = verify_chain(db)
    return {"success": True, "data": result}


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
