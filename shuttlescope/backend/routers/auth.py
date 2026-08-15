"""Authentication and user-management routes."""

import base64
import hashlib
import hmac as _hmac_mod
import logging
import os
import re as _re
import secrets as _secrets
import struct
import threading
import time
import urllib.parse
import uuid as _uuid_mod
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

import bcrypt as _bcrypt_lib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StrictBool, field_validator, model_validator
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db
from backend.db.models import (
    MfaRecoveryCode, Player, PlayerPageAccess, Team, User, UserConsent,
)

# llm = 汎用 LLM チャット (/#/llm)、badminton = バドミントン解析アプリ。
# admin が player_page_access 経由でユーザ単位に付与する (自己付与不可)。
GRANTABLE_PAGES = {"prediction", "expert_labeler", "llm", "badminton"}

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


# Round 258 R3 P1 fix (F8): _IP_LOGIN_TIMES dict は IPv6 ローテーション攻撃で
# 無制限に key が積もり memory DoS を引き起こす。LRU で 100k key cap を設けつつ、
# 100 回に 1 回程度 expired key を sweep する。
_IP_RATE_MAX_KEYS = 100_000
_IP_RATE_SWEEP_INTERVAL = 100
_IP_RATE_SWEEP_COUNTER = [0]  # mutable for inner closure


def _check_ip_rate_limit(ip: Optional[str]) -> None:
    if not ip:
        return
    now = time.time()
    cutoff = now - _IP_RATE_WINDOW
    with _IP_RATE_LOCK:
        # Periodic sweep
        _IP_RATE_SWEEP_COUNTER[0] += 1
        if _IP_RATE_SWEEP_COUNTER[0] >= _IP_RATE_SWEEP_INTERVAL:
            _IP_RATE_SWEEP_COUNTER[0] = 0
            empty_keys = [k for k, v in _IP_LOGIN_TIMES.items() if not [t for t in v if t > cutoff]]
            for k in empty_keys:
                _IP_LOGIN_TIMES.pop(k, None)
            # 万一 cap を超えたら任意の古い key を 1k 件落とす (簡易 LRU)
            if len(_IP_LOGIN_TIMES) > _IP_RATE_MAX_KEYS:
                drop_n = len(_IP_LOGIN_TIMES) - _IP_RATE_MAX_KEYS + 1000
                # times list の最大値が小さい順 (古い IP) を削る
                ordered = sorted(_IP_LOGIN_TIMES.items(),
                                 key=lambda kv: max(kv[1]) if kv[1] else 0)
                for k, _ in ordered[:drop_n]:
                    _IP_LOGIN_TIMES.pop(k, None)
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
    """パスワード強度を検証する。不足の場合 HTTPException(422) を送出。

    ポリシー:
    - 最低長 (_PASSWORD_MIN_LENGTH) 以上
    - bcrypt 72-byte 制限以下
    - 文字種 4 区分 (大文字 / 小文字 / 数字 / 記号) のうち **少なくとも 3 種類** を含む
      （player を含む全ロール共通。覚えやすさと強度のバランス）
    """
    if len(password) < _PASSWORD_MIN_LENGTH:
        raise HTTPException(422, f"パスワードは{_PASSWORD_MIN_LENGTH}文字以上が必要です")
    # bcrypt 72-byte truncation 対策。文字数ではなく UTF-8 バイト数で計測する。
    if len(password.encode("utf-8")) > _PASSWORD_MAX_BYTES:
        raise HTTPException(
            422,
            f"パスワードは {_PASSWORD_MAX_BYTES} バイト以下にしてください "
            f"(英数記号 {_PASSWORD_MAX_BYTES} 文字 / 日本語 ~24 文字)",
        )
    classes = 0
    if _re.search(r'[a-z]', password):
        classes += 1
    if _re.search(r'[A-Z]', password):
        classes += 1
    if _re.search(r'\d', password):
        classes += 1
    if _re.search(r'[!@#$%^&*()\-_=+\[\]{}|;:,.<>?/~`]', password):
        classes += 1
    if classes < 3:
        raise HTTPException(
            422,
            "パスワードは大文字 / 小文字 / 数字 / 記号 のうち少なくとも 3 種類を含めてください",
        )


# ── TOTP（標準ライブラリのみ実装、pyotp 不要） ───────────────────────────────

def _totp_generate_secret() -> str:
    """20バイトのランダムシークレットを base32 エンコードで返す。"""
    return base64.b32encode(os.urandom(20)).decode("utf-8").rstrip("=")


def _hotp_value(secret: str, counter: int) -> int:
    # SHA-1 は RFC 4226 (HOTP) / RFC 6238 (TOTP) が定める既定アルゴリズムで、
    # Google Authenticator や iOS パスワードなど実在の認証アプリが確実に対応する
    # のはこれだけ。他へ変えると登録済み端末が一斉に無効になる。
    # HMAC-SHA1 の安全性は SHA-1 の衝突耐性に依存しないため (MAC としては現在も
    # 安全)、ここでの SHA-1 使用は既知の弱点に当たらない。
    padding = "=" * (-len(secret) % 8)
    key = base64.b32decode(secret.upper() + padding)
    msg = struct.pack(">Q", counter)
    h = _hmac_mod.new(key, msg, hashlib.sha1).digest()  # DevSkim: ignore DS126858
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset: offset + 4])[0] & 0x7FFFFFFF
    return code % 1_000_000


# decrypt_field が復号に失敗したときに返すセンチネル。これを base32 secret として
# 扱うと base32 デコードで例外になり 500 を返す (= リカバリコード経路まで巻き添え)。
# 「MFA が使えない」ことを明示的に検出するため、値として弾く。
_UNUSABLE_SECRET_SENTINELS = (
    "[ENCRYPTED:KEY_MISSING]",
    "[ENCRYPTED:INVALID]",
    "[ENCRYPTED:ERROR]",
)


def _totp_secret_usable(secret: Optional[str]) -> bool:
    """保存済み secret が TOTP 検証に使える形かを返す。

    鍵の紛失・不一致・改ざんで復号できなかった場合、DB からは平文ではなく
    センチネル文字列が返る。これを検証に渡さない。
    """
    if not secret or not isinstance(secret, str):
        return False
    return secret not in _UNUSABLE_SECRET_SENTINELS


def _verify_totp(secret: str, code: str) -> bool:
    """前後1ウィンドウ（±30秒）を許容してTOTPコードを検証する。

    復号不能な secret は「一致しない」ではなく使用不可として False を返す
    (呼び出し側で 503 相当を返せるよう _totp_secret_usable で事前判定すること)。
    """
    if not _totp_secret_usable(secret):
        logger.error(
            "[auth] TOTP secret を復号できません。SS_FIELD_ENCRYPTION_KEY を確認してください。"
        )
        return False
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
        # algorithm=SHA1 は otpauth URI の既定値 (RFC 6238)。_hotp_value 側の
        # 実装と一致させる必要があり、認証アプリ互換のため変更不可。
        f"?secret={secret}&issuer={urllib.parse.quote(issuer)}&algorithm=SHA1&digits=6&period=30"  # DevSkim: ignore DS126858
    )


# ── MFA リカバリコード ───────────────────────────────────────────────────────
#
# 認証アプリの紛失やサーバ/端末の時計ズレで TOTP が通らなくなった際の、
# 唯一の自力復旧手段。2026-07 の締め出し障害 (w32time 停止による時計ズレ) では
# この手段が存在せず、DB を直接書き換えるしか復旧方法が無かった。

# base32 準拠 (0/1/8/9 を含まない = 目視誤読しにくい)
_RECOVERY_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_RECOVERY_CODE_LEN = 16          # 16 文字 × 5bit = 80bit
_RECOVERY_CODE_COUNT = 10        # 1 回の発行で 10 本
_RECOVERY_GROUP = 4              # XXXX-XXXX-XXXX-XXXX 表示


def _generate_recovery_code() -> str:
    """80bit の使い捨てコードを XXXX-XXXX-XXXX-XXXX 形式で返す。"""
    raw = "".join(_secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_CODE_LEN))
    return "-".join(
        raw[i: i + _RECOVERY_GROUP] for i in range(0, _RECOVERY_CODE_LEN, _RECOVERY_GROUP)
    )


def _normalize_recovery_code(code: str) -> str:
    """入力揺れ (小文字・ハイフン有無・空白) を吸収して比較用に正規化する。"""
    if not code:
        return ""
    return "".join(ch for ch in code.upper() if ch in _RECOVERY_ALPHABET)


def _hash_recovery_code(code: str) -> str:
    """正規化済みコードの SHA-256 hex を返す。

    パスワードと違いコードは 80bit の一様乱数なので、辞書攻撃・レインボー
    テーブルいずれも成立しない。salt 付き低速ハッシュ (bcrypt) にすると
    ログイン 1 回あたり発行数ぶんの検証が必要になり CPU 消費型 DoS を招くため、
    ハッシュ直引きできる高速ハッシュを選ぶ。
    """
    return hashlib.sha256(_normalize_recovery_code(code).encode("utf-8")).hexdigest()


def _issue_recovery_codes(db: Session, user_id: int) -> list[str]:
    """既存コードを全て破棄し、新しいコード一式を発行して平文を返す。

    平文は返り値としてのみ存在し、DB にはハッシュしか残らない。
    """
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user_id).delete(
        synchronize_session=False
    )
    codes: list[str] = []
    for _ in range(_RECOVERY_CODE_COUNT):
        code = _generate_recovery_code()
        codes.append(code)
        db.add(
            MfaRecoveryCode(
                user_id=user_id,
                code_hash=_hash_recovery_code(code),
                created_at=datetime.utcnow(),
            )
        )
    db.commit()
    return codes


def _consume_recovery_code(db: Session, user_id: int, code: str, ip: Optional[str]) -> bool:
    """リカバリコードを 1 本消費する。成功なら True。

    二重使用防止のため、`used_at IS NULL` を条件に含めた UPDATE の
    rowcount で判定する (SELECT してから UPDATE すると、同一コードの
    同時 2 リクエストが両方成功しうる)。
    """
    normalized = _normalize_recovery_code(code)
    # 長さが合わない入力は DB を叩くまでもなく棄却する。
    if len(normalized) != _RECOVERY_CODE_LEN:
        return False
    code_hash = _hash_recovery_code(normalized)
    updated = (
        db.query(MfaRecoveryCode)
        .filter(
            MfaRecoveryCode.user_id == user_id,
            MfaRecoveryCode.code_hash == code_hash,
            MfaRecoveryCode.used_at.is_(None),
        )
        .update(
            {"used_at": datetime.utcnow(), "used_ip": ip},
            synchronize_session=False,
        )
    )
    db.commit()
    return updated > 0


def _emit_recovery_security_event(
    user_id: int, ip: Optional[str], detail: str, severity: str = "warning"
) -> None:
    """リカバリコードの使用/再発行を security_events に残す。

    MFA を迂回できる操作なので、正規利用でも「いつ・どこから」を追える必要が
    ある (アカウント乗っ取りの初動がリカバリコード使用であることは多い)。
    """
    try:
        from backend.utils.security_log import emit_security_event
        emit_security_event(
            "mfa_recovery",
            severity=severity,
            ip_addr=ip,
            user_id=user_id,
            details={"detail": detail},
        )
    except Exception:  # noqa: BLE001 - 監査記録の失敗で認証を落とさない
        logger.warning("failed to emit mfa_recovery security event", exc_info=True)


def _recovery_codes_remaining(db: Session, user_id: int) -> int:
    return (
        db.query(MfaRecoveryCode)
        .filter(
            MfaRecoveryCode.user_id == user_id,
            MfaRecoveryCode.used_at.is_(None),
        )
        .count()
    )


# ── ログインID バリデーション ─────────────────────────────────────────────────

_ASCII_WS = " \t\r\n\x0b\x0c"


def _normalize_login_id(value: Optional[str]) -> str:
    # Round 279 fix: 既定 str.strip() は Unicode whitespace (U+00A0 NBSP,
    # U+200B ZWSP, U+3000 IDEOGRAPHIC SPACE, U+FEFF BOM 等) も削除するため、
    # "adminTakeuchi_" + NBSP のような入力が DB lookup で admin と衝突する
    # fuzzy match を引き起こす。ASCII whitespace のみに限定する。
    # 加えて Pydantic 層 (_reject_invalid_chars_in_id) で Unicode whitespace
    # 自体を 422 で reject しているため、ここに到達する時点で残らない想定。
    return (value or "").strip(_ASCII_WS)


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
    #
    # Round 258 R18 P1 fix (R18a-2 P1-1): 旧コードは CF-Connecting-IP を **無条件**
    # に信頼していたが、本プロセスはローカル port 8765 にも bind されており
    # cloudflared 経由でない LAN クライアントが直接到達する経路がある (cluster /
    # SSH トンネル / Tailscale)。その場合 attacker が `CF-Connecting-IP` を
    # 任意に書き換えてレート制限を回避できる。
    # 修正: socket peer が **loopback (cloudflared sidecar)** のときだけ
    # CF-Connecting-IP を採用し、それ以外は socket IP を返す。
    cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
    if cf_ip:
        try:
            from backend.utils.control_plane import is_loopback_request
            if is_loopback_request(request):
                return cf_ip
        except Exception:
            # control_plane が読み込めないか request 解釈に失敗した場合は
            # 安全側に倒し、socket peer の IP を返す。
            pass
    return request.client.host if request.client else None


# ── アカウントロックアウト ────────────────────────────────────────────────────

def _check_lockout(user: User) -> None:
    """ロック中なら HTTPException を送出。

    Round 280 fix: ロック中の応答が 429 + 「アカウントがロックされています」
    本文だったため、非存在ユーザ (常時 401 "login failed") との挙動差で
    任意 username に対し「3 回 wrong pw → 応答が変わるか」で実在判定が
    成立していた (username enumeration oracle)。

    対策: 公開 login 経路では lockout を **401 "login failed"** に偽装し、
    non-existent / wrong-pw / locked の 3 状態を外部から不可分にする。
    本来のロック残時間は admin 専用 endpoint (auth-users 等) からのみ可視。

    ロック期間が経過していたら failed_attempts を 0 に戻し、解除直後の 1 回失敗で
    再ロックされる挙動を防ぐ (新規 _MAX_FAILED_ATTEMPTS=3 回まで失敗を許容する)。
    """
    if user.locked_until and user.locked_until > datetime.utcnow():
        # 旧: 429 + 残時間明示 → 列挙オラクル
        # 新: 401 + 汎用 "login failed" (非存在 user と同 body / 同 status)
        raise HTTPException(
            status_code=401,
            detail="login failed",
        )
    # round155 fix: 元実装は `locked_until is None` でもリセットしてしまい
    # 通常の連続失敗時に failed_attempts が永遠に 0 に戻り続けて lockout が
    # 一度も発動しなかった。ロック解除「後」のみカウンタを 0 に戻す。
    # (locked_until が past = ロック明け、None = まだ一度もロックされていない)
    if (user.failed_attempts or 0) > 0 and user.locked_until is not None and user.locked_until <= datetime.utcnow():
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
    """Round 258 R8/R10 P1 fix (deep audit F3 + regression): lockout race を
    **単一 atomic UPDATE** で塞ぐ。

    R8 fix では UPDATE → commit → refresh → 第二 UPDATE → commit の 2 段構成だった
    ため、2 commit の間に並列 `_check_lockout` が `failed_attempts=MAX, locked_until=NULL`
    を観測して「未 lock」と判定し、ブルートフォース budget が +1 する race window が
    残っていた。R10 では CASE 句で increment + lock 確定を 1 statement で実行し、
    その間 transaction 内で他リクエストが「中間状態」を観測できないようにする。
    """
    from backend.utils.access_log import log_access
    from backend.db.models import User as _UserMdl
    from sqlalchemy import case as _case_sql, func as _func_sql
    now = datetime.utcnow()
    lock_until = now + timedelta(minutes=_LOCKOUT_MINUTES)

    # 単一 atomic UPDATE:
    #   failed_attempts = failed_attempts + 1
    #   locked_until = CASE
    #     WHEN failed_attempts + 1 >= MAX
    #          AND (locked_until IS NULL OR locked_until <= now)  -- rolling lock 阻止
    #     THEN lock_until
    #     ELSE locked_until
    #   END
    new_attempts = _UserMdl.failed_attempts + 1
    db.query(_UserMdl).filter(_UserMdl.id == user.id).update(
        {
            "failed_attempts": new_attempts,
            "locked_until": _case_sql(
                (
                    (
                        (new_attempts >= _MAX_FAILED_ATTEMPTS)
                        & (
                            (_UserMdl.locked_until.is_(None))
                            | (_UserMdl.locked_until <= now)
                        )
                    ),
                    lock_until,
                ),
                else_=_UserMdl.locked_until,
            ),
        },
        synchronize_session=False,
    )
    db.commit()
    db.refresh(user)
    if user.failed_attempts >= _MAX_FAILED_ATTEMPTS:
        log_access(db, "account_locked", user_id=user.id, ip_addr=ip,
                   details={"reason": reason, "attempts": user.failed_attempts})
        # Round 280 fix: ロック確定時の 429 + 「N 回に達しました」本文は
        # 「存在ユーザが MAX 回連続失敗した」事実を外部に露呈する
        # enumeration oracle。非存在 user 経路と同じ 401 "login failed"
        # に偽装する。account_locked event は内部 audit log に残るので
        # 運用側は引き続き把握可能。
        raise HTTPException(status_code=401, detail="login failed")
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

    @field_validator("username", "identifier", mode="after")
    @classmethod
    def _reject_invalid_chars_in_id(cls, v: Optional[str]) -> Optional[str]:
        # round 233 R7-A: PostgreSQL の text 列は NUL byte を受け付けず、
        # ValueError 経由で 500 リークする。Pydantic 層で早期拒否する。
        # 同時に C0 制御文字も拒否 (audit log injection / log noise 抑制)。
        if v is None:
            return v
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in v):
            from fastapi import HTTPException as _HTTP
            raise _HTTP(status_code=422, detail="username/identifier に制御文字を含めることはできません")
        # Round 279 fix: Unicode whitespace (U+00A0 NBSP, U+200B ZWSP,
        # U+3000 IDEOGRAPHIC SPACE, U+FEFF BOM 等) を含む入力は、
        # 後段の str.strip() が削除して DB lookup を fuzzy match させる
        # (例: "adminTakeuchi_" + NBSP が admin と衝突)。
        # 認証系は string-exact 同一性が前提のため、Unicode whitespace を
        # 含む username/identifier は API 境界で 422 拒否する。
        # email アドレスを identifier に入れるケースも RFC 5321/5322 で
        # whitespace は禁止 (quoted-string 形式すら通常 reject) のため副作用なし。
        import unicodedata as _ud
        for ch in v:
            cat = _ud.category(ch)
            # Zs = Space_Separator, Zl = Line_Separator, Zp = Paragraph_Separator
            if cat in ("Zs", "Zl", "Zp"):
                from fastapi import HTTPException as _HTTP
                raise _HTTP(status_code=422,
                            detail="username/identifier に空白文字を含めることはできません")
            # U+200B-200D (ZWSP/ZWNJ/ZWJ), U+2060 (WJ), U+FEFF (BOM) は
            # category=Cf (format) で Zs にならないが whitespace-likely。明示 reject。
            if ord(ch) in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF):
                from fastapi import HTTPException as _HTTP
                raise _HTTP(status_code=422,
                            detail="username/identifier にゼロ幅文字を含めることはできません")
        return v


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
    code: Optional[str] = Field(None, max_length=16)
    # 認証アプリを失った / 端末の時計がずれた場合の代替。
    # 表示形式は XXXX-XXXX-XXXX-XXXX (16 文字 + ハイフン 3)。区切り文字の
    # 揺れを許容するため上限は緩めに 32。
    recovery_code: Optional[str] = Field(None, max_length=32)

    @model_validator(mode="after")
    def _exactly_one_credential(self):
        # 両方同時指定を許すと「TOTP が通らなければリカバリコードも試す」形の
        # 1 リクエスト 2 回試行になり、ブルートフォース計数が実質半分になる。
        if bool(self.code) == bool(self.recovery_code):
            raise ValueError("code または recovery_code のいずれか一方を指定してください")
        return self


class MfaRecoveryCodesResponse(BaseModel):
    """リカバリコードの平文を返す唯一のタイミングの応答。

    平文は DB に保存しないため、この応答を逃すと再発行しか復旧手段がない。
    """
    success: bool = True
    recovery_codes: list[str]
    message: str = ""


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

# Round62 で 104ms、Round62 v2 で 58ms のタイミング差が観測されたため、login 失敗系の
# 処理全体を最小総時間まで pad することで bcrypt + DB I/O の差分を観測不能にする
# (CWE-204 対策)。実測 P99 ~2.0s を上回る 2.5s を採用し、確実にパディングが発火するようにする。
# また 0〜150ms のランダム jitter を加えて統計的解析を困難にする。
_LOGIN_MIN_RESPONSE_SEC = 2.5
_LOGIN_JITTER_MAX_SEC = 0.15

def _login_constant_time_pad(start_ts: float) -> None:
    """login 処理開始からの経過時間が _LOGIN_MIN_RESPONSE_SEC + jitter 未満なら sleep で補う."""
    import time as _t
    import secrets as _s
    jitter = _s.randbelow(int(_LOGIN_JITTER_MAX_SEC * 1000)) / 1000.0
    target = _LOGIN_MIN_RESPONSE_SEC + jitter
    elapsed = _t.perf_counter() - start_ts
    remaining = target - elapsed
    if remaining > 0:
        _t.sleep(remaining)


def _pad_and_raise(start_ts: float, status_code: int, detail: str) -> None:
    """指定ステータスを raise する前に固定時間パディングを行う."""
    _login_constant_time_pad(start_ts)
    raise HTTPException(status_code=status_code, detail=detail)


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    import time as _t_login
    _login_t0 = _t_login.perf_counter()
    try:
        return _login_impl(req, request, db, _login_t0)
    except HTTPException as e:
        # 認証失敗系 (401/429) のみ固定時間パディングを適用してから再 raise
        # 成功 (200) は user 経験を損なわないようパッドしない
        if e.status_code in (401, 422, 429):
            _login_constant_time_pad(_login_t0)
        raise


def _mfa_challenge_if_enabled(user: User, db: Session, ip: Optional[str]):
    """MFA 有効ユーザにはフル JWT を渡さず、プリ認証トークンを返す。

    MFA 有効なら LoginResponse(mfa_required=True) を、無効なら None を返す。

    このゲートは全ての「秘密情報を検証してトークンを発行する」grant_type から
    呼ぶこと。credential だけに実装されていた結果、password / pin grant では
    MFA が完全に素通りしていた (= username+password を知る攻撃者が
    grant_type を変えるだけで MFA を迂回できた)。
    """
    if not getattr(user, "totp_enabled", False):
        return None
    mfa_token = create_access_token(user.id, "mfa_pending", hours=5 / 60)
    log_access(db, "login_mfa_required", user_id=user.id, ip_addr=ip)
    return LoginResponse(mfa_required=True, mfa_token=mfa_token)


def _login_impl(req: "LoginRequest", request: Request, db: Session, _login_t0: float):
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

        # M-A4: identifier は username または email のいずれでも受け付ける
        # ('@' を含むなら email として、それ以外は username として検索)
        if "@" in identifier:
            user = db.query(User).filter(User.email == identifier).first()
        else:
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
        challenge = _mfa_challenge_if_enabled(user, db, ip)
        if challenge is not None:
            return challenge

        token = create_access_token(user.id, user.role, user.player_id, team_name=user.team_name, team_id=user.team_id)
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
        # M-A4: identifier も username もどちらも受け付け、'@' を含めば email 検索
        identifier_pw = (req.identifier or req.username or "").strip()
        if not identifier_pw or not req.password:
            raise HTTPException(status_code=422, detail="username and password are required")
        if "@" in identifier_pw:
            user = db.query(User).filter(User.email == identifier_pw).first()
        else:
            user = db.query(User).filter(User.username == identifier_pw).first()
        if not user or not user.hashed_credential:
            _verify_password(req.password, _DUMMY_BCRYPT_HASH)
            log_access(db, "login_failed", details={"reason": "user_not_found", "username": identifier_pw}, ip_addr=ip)
            _timing_padding_db_write(db)
            raise HTTPException(status_code=401, detail="login failed")
        _check_lockout(user)
        if not _verify_password(req.password, user.hashed_credential):
            _on_login_failure(user, db, ip, "wrong_password")
        _on_login_success(user, db)
        # credential grant と同様に MFA を要求する (grant_type を変えるだけで
        # MFA を迂回できてはならない)。
        challenge = _mfa_challenge_if_enabled(user, db, ip)
        if challenge is not None:
            return challenge
        token = create_access_token(user.id, user.role, user.player_id, team_name=user.team_name, team_id=user.team_id)
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
            # Select grants must match the requested role exactly.
            if not user or user.role != role:
                raise HTTPException(status_code=404, detail="user not found")
            # Local select login still honors lockout state.
            _check_lockout(user)
        else:
            user = db.query(User).filter(User.role == role).first()
            if not user:
                token = create_access_token(0, role)
                log_access(db, "login", details={"role": role, "method": "select"}, ip_addr=ip)
                return LoginResponse(access_token=token, role=role, user_id=0)
            # ユーザを暗黙選択した場合も lockout を尊重する
            _check_lockout(user)
        token = create_access_token(user.id, user.role, user.player_id, team_name=user.team_name, team_id=user.team_id)
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
        # player ロールでも MFA を有効にできるため、pin grant でも同じゲートを通す。
        challenge = _mfa_challenge_if_enabled(user, db, ip)
        if challenge is not None:
            return challenge
        token = create_access_token(user.id, user.role, user.player_id, team_name=user.team_name, team_id=user.team_id)
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
    # MFA completion must re-check lockout state before issuing a token.
    _check_lockout(user)
    if req.recovery_code:
        # 認証アプリ紛失 / 時計ズレ時の復旧経路。コードは単回使用で消費される。
        if not _consume_recovery_code(db, user_id, req.recovery_code, ip):
            _record_mfa_failure(user_id)
            raise HTTPException(status_code=401, detail="リカバリコードが無効か、既に使用済みです")
        remaining = _recovery_codes_remaining(db, user_id)
        # 「誰かがリカバリコードを使った」は不正アクセスの兆候にもなるため、
        # 通常ログインとは区別して監査に残す。
        log_access(db, "login_mfa_recovery_used", user_id=user.id, ip_addr=ip)
        _emit_recovery_security_event(
            user.id, ip, f"MFA recovery code consumed (remaining={remaining})"
        )
    else:
        # 鍵の紛失・不一致で secret が復号できないケースを「コードが違う」と伝えると、
        # 運用者が延々と正しいコードを打ち続けることになる。復旧手段
        # (リカバリコード) へ誘導できるよう区別して返す。
        if not _totp_secret_usable(user.totp_secret):
            logger.error("[auth] MFA login: secret を復号できません (user_id=%s)", user_id)
            raise HTTPException(
                status_code=503,
                detail="MFA を検証できません。リカバリコードでログインし、管理者に連絡してください。",
            )
        if not _verify_totp(user.totp_secret, req.code or ""):
            _record_mfa_failure(user_id)
            raise HTTPException(status_code=401, detail="認証コードが無効です")
    token = create_access_token(user.id, user.role, user.player_id, team_name=user.team_name, team_id=user.team_id)
    if not req.recovery_code:
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
    # Round 258 R4 F7 fix: 既に setup 中 (totp_secret 設定済 / totp_enabled=False) の場合
    # 攻撃者が再生成して正規ユーザの QR スキャンを差し替え、自分の secret を仕込むのを防ぐ。
    # 同 secret を返却して setup 進行を冪等化する (ユーザは前回の QR を引き続き使える)。
    existing_secret = getattr(user, "totp_secret", None)
    if existing_secret:
        return MfaSetupResponse(secret=existing_secret,
                                otpauth_uri=_totp_uri(existing_secret, user.username))
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
# Round 258 R9 F-1 fix: 不正な user_id を任意に append できると dict が無制限に
# 膨らむ。periodic LRU sweep + cap で memory DoS を抑止する。
_MFA_MAX_KEYS = 10_000
_MFA_SWEEP_EVERY = 100
_MFA_SWEEP_COUNTER = [0]


def _mfa_sweep_locked(now: float) -> None:
    cutoff = now - _MFA_WINDOW_SEC
    stale = [uid for uid, arr in _mfa_failures.items()
             if not arr or max(arr) < cutoff]
    for uid in stale:
        _mfa_failures.pop(uid, None)
    if len(_mfa_failures) > _MFA_MAX_KEYS:
        # それでも溢れる → 最古順に半分落とす (DoS 緩和; legitimate user も多少影響)
        ordered = sorted(_mfa_failures.items(),
                         key=lambda kv: max(kv[1]) if kv[1] else 0)
        drop = len(_mfa_failures) - _MFA_MAX_KEYS // 2
        for uid, _ in ordered[:drop]:
            _mfa_failures.pop(uid, None)


def _check_mfa_brute_limit(user_id: int) -> None:
    """MFA コード推測に対する rate limit。"""
    if not user_id:
        return
    now = _t_mfa.time()
    with _mfa_lock:
        # Periodic LRU sweep (R9 F-1 fix)
        _MFA_SWEEP_COUNTER[0] += 1
        if _MFA_SWEEP_COUNTER[0] >= _MFA_SWEEP_EVERY:
            _MFA_SWEEP_COUNTER[0] = 0
            _mfa_sweep_locked(now)
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


@router.post("/mfa/confirm", response_model=MfaRecoveryCodesResponse)
def mfa_confirm(req: MfaCodeRequest, request: Request, db: Session = Depends(get_db)):
    """TOTPコードを検証してMFAを有効化し、リカバリコードを発行する。

    リカバリコードの平文を返すのはこの応答と /mfa/recovery/regenerate だけ。
    DB にはハッシュしか残らないため、ここで控えを取らないと復旧手段は
    再発行 (= TOTP が通る状態が前提) のみになる。
    """
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
    codes = _issue_recovery_codes(db, user.id)
    return MfaRecoveryCodesResponse(
        recovery_codes=codes,
        message=(
            "MFAが有効化されました。リカバリコードを安全な場所に保管してください。"
            "この画面を閉じると再表示できません。"
        ),
    )


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
    # MFA を無効化したらリカバリコードも失効させる。残しておくと、次に MFA を
    # 有効化したとき「前回の紙のコード」がまだ通ってしまう。
    db.query(MfaRecoveryCode).filter(MfaRecoveryCode.user_id == user.id).delete(
        synchronize_session=False
    )
    db.commit()
    log_access(db, "mfa_disabled", user_id=user.id)
    return {"success": True, "message": "MFAが無効化されました"}


@router.post("/mfa/recovery/regenerate", response_model=MfaRecoveryCodesResponse)
def mfa_recovery_regenerate(
    req: MfaCodeRequest, request: Request, db: Session = Depends(get_db)
):
    """TOTPコードを確認してリカバリコードを再発行する（既存コードは全て失効）。

    使い切った場合や、控えを紛失した場合に使う。
    """
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")
    # 漏洩した access token による総当たりを遮断 (他 MFA 経路と共通カウンタ)。
    _check_mfa_brute_limit(ctx.user_id)
    user = db.get(User, ctx.user_id)
    if not user or not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="MFAは有効化されていません")
    if not _verify_totp(user.totp_secret, req.code):
        _record_mfa_failure(ctx.user_id)
        raise HTTPException(status_code=400, detail="認証コードが無効です")
    codes = _issue_recovery_codes(db, user.id)
    log_access(db, "mfa_recovery_regenerated", user_id=user.id, ip_addr=_get_ip(request))
    _emit_recovery_security_event(
        user.id, _get_ip(request), "MFA recovery codes regenerated", severity="info"
    )
    return MfaRecoveryCodesResponse(
        recovery_codes=codes,
        message=(
            "リカバリコードを再発行しました。以前のコードは全て無効です。"
            "この画面を閉じると再表示できません。"
        ),
    )


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
    return {
        "success": True,
        "mfa_enabled": bool(user.totp_enabled),
        # 残数のみ返す (コード本体は DB にハッシュしか無いので返しようがない)。
        # 0 本になったら再発行を促す UI 判断に使う。
        "recovery_codes_remaining": _recovery_codes_remaining(db, user.id),
    }


# ── ブートストラップステータス ───────────────────────────────────────────────

@router.get("/bootstrap-status", response_model=BootstrapStatusResponse)
def bootstrap_status(request: Request, db: Session = Depends(get_db)):
    """Expose initial-admin bootstrap readiness without revealing secrets.

    SEC / 攻撃集計 #3: 本番姿勢 (Cloudflare 公開等) では匿名で運用状態
    (admin 在席 / 初期化フロー進行度) を取得できないように admin 認証必須。
    LAN / Electron 単体の場合は Electron 初回 UX のため匿名のまま許可。
    """
    from backend.config import settings as _settings_bs
    if _settings_bs.is_production_posture:
        from backend.utils.auth import get_auth as _get_auth_bs
        ctx = _get_auth_bs(request)
        if ctx.role != "admin":
            # 匿名 / 非 admin にはバイナリの ready 判定だけ返して内部状態を隠す
            status = _bootstrap_admin_status(db)
            return BootstrapStatusResponse(
                has_admin=bool(status.has_admin),
                bootstrap_configured=False,
            )
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

    import jwt as _pyjwt
    from jwt import PyJWTError
    try:
        payload = _pyjwt.decode(
            auth_header[7:], settings.SECRET_KEY, algorithms=["HS256"]
        )
        jti = payload.get("jti")
        exp = payload.get("exp")
        if jti and exp:
            expires_at = datetime.utcfromtimestamp(exp)
            revoke_token(jti, getattr(ctx, "user_id", None), expires_at)
    except PyJWTError:
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
    # round142 J-1 fix: refresh token brute force 防御 (false-token enumeration)
    _check_ip_rate_limit(_get_ip(request))
    rotated = rotate_refresh_token(req.refresh_token)
    if not rotated:
        raise HTTPException(status_code=401, detail="refresh token invalid or expired")
    user = db.get(User, rotated["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="user not found")
    # Refresh must re-check lockout state before issuing a token.
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
    for _i in range(len(pick) - 1, 0, -1):
        _j = _secrets.randbelow(_i + 1)
        pick[_i], pick[_j] = pick[_j], pick[_i]
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
    # Round 258 R20 P2 fix (R20 P2-2): access token (15min) も per-user revoke epoch
    # で即時失効させる。これで盗まれた access token が password rotation 後に
    # 残存利用される 15 分の窓を閉じる。
    # Round 258 R21 P0 fix (R21 P0-1): 旧コードは exception を warn ログだけで
    # 握り潰していたため、DB 書込み失敗時に password 変更だけ成功して access
    # token 失効が走らない silent failure があった。raise に変更して 500 で
    # 早期検知できるようにする (sentinel uniqueness は jwt_utils 側で uuid 補強済)。
    from backend.utils.jwt_utils import revoke_all_for_user as _revoke_all_for_user
    try:
        _revoke_all_for_user(user.id)
    except Exception as exc:
        logger.error("revoke_all_for_user failed (password change) user_id=%s: %s", user.id, exc)
        raise HTTPException(status_code=500, detail="access token 失効処理に失敗しました")
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
    # Round 258 R20 P2 fix (R20 P2-2) + R21 P0 fix (R21 P0-1): access token も即時失効。
    # silent failure を避けるため raise に倒す。
    from backend.utils.jwt_utils import revoke_all_for_user as _revoke_all_for_user
    try:
        _revoke_all_for_user(user.id)
    except Exception as exc:
        logger.error("revoke_all_for_user failed (admin reset) user_id=%s: %s", user.id, exc)
        raise HTTPException(status_code=500, detail="access token 失効処理に失敗しました")
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

    # player と llm は「実際に付与された grant のみ」。admin/analyst/coach は従来どおり
    # GRANTABLE_PAGES 全付与 (信頼ロール)。llm 専用ユーザに badminton 系ページを
    # frontend で見せない/到達させないため、player と同じ扱いにする。
    if ctx.role in ("player", "llm") and user_id and user:
        page_access = _get_page_access(user_id, user, db)
    else:
        page_access = list(GRANTABLE_PAGES)

    # 任意同意の未回答検出: 必須同意 (consent_required) が落ちていても、optional
    # 同意で 1 度も回答していない type があれば popup を再表示する。
    # 「あとで」を押したユーザの再促し用 (実装方針: optional は record 無し=未回答)。
    #
    # role='llm' (汎用 LLM チャット専用ユーザ) は badminton 機能を一切持たず、
    # _OPTIONAL_CONSENT_TYPES は全て badminton 固有の任意同意
    # (体組成開示 / AI 学習 / 学術研究 等) なので、これらの未回答で popup を
    # 再促すのは無意味かつ不適切。llm-only には optional 同意を要求しない
    # (必須同意 service_delivery / beta_agreement は引き続き必要)。
    optional_pending = False
    if user is not None and ctx.role != "llm":
        recorded_optional_types = {
            row[0]
            for row in db.query(UserConsent.consent_type)
            .filter(UserConsent.user_id == user.id)
            .filter(UserConsent.consent_type.in_(list(_OPTIONAL_CONSENT_TYPES)))
            .distinct()
            .all()
        }
        optional_pending = len(_OPTIONAL_CONSENT_TYPES - recorded_optional_types) > 0

    return {
        "role": ctx.role,
        "player_id": ctx.player_id,
        "user_id": user_id,
        "team_name": ctx.team_name,
        "display_name": (user.display_name or user.username) if user else None,
        "page_access": page_access,
        "mfa_enabled": bool(user.totp_enabled) if user else False,
        # M-A: 自分の email と検証状態 (フロントの「再送」UI 等で参照)
        "email": getattr(user, "email", None) if user else None,
        "email_verified": bool(getattr(user, "email_verified_at", None)) if user else False,
        # GDPR Article 7 / APPI 第18条: 同意未取得の場合 frontend は
        # /onboarding/consent へリダイレクトする
        "consent_required": bool(getattr(user, "consent_required", True)) if user else True,
        # 任意同意のうち 1 度も回答していない type が残っているか。
        # True なら frontend は popup を表示するが「あとで」だけは押せる軽量 mode。
        "optional_consent_pending": optional_pending,
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
    """Round 258 R8 P0 fix (deep audit F1): admin role の DB 二重検証。

    旧コードは JWT payload の `role` だけで判定していたため、admin が DB 上で
    demote されたり lock されたりしても token 期限切れまで admin 操作が通った。
    incident response (admin demotion / 強制 lockout) が機能不全になる重大な穴。
    本修正は JWT を信用した上で、必ず DB から user を再取得して
    role / locked_until / awaiting_admin_approval を再確認する。
    """
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin role required")
    # DB 再検証
    if ctx.user_id is None:
        raise HTTPException(status_code=403, detail="admin role required")
    try:
        from backend.db.database import SessionLocal
        from backend.db.models import User
        with SessionLocal() as _db:
            u = _db.get(User, int(ctx.user_id))
            if u is None or (u.role or "") != "admin":
                raise HTTPException(status_code=403, detail="admin role required (DB re-check failed)")
            if getattr(u, "awaiting_admin_approval", False):
                raise HTTPException(status_code=403, detail="admin pending approval")
            from datetime import datetime as _dt_admin
            lu = getattr(u, "locked_until", None)
            if lu is not None and lu > _dt_admin.utcnow():
                raise HTTPException(status_code=403, detail="admin account is locked")
            # Round 281+ fix: admin role に MFA enrollment を必須化する。
            # config SS_REQUIRE_ADMIN_MFA で disable 可能 (緊急時のみ)。
            # /api/auth/mfa/setup / /api/auth/mfa/confirm は get_auth gate
            # を使い _require_admin を呼ばないので本判定の影響を受けない。
            from backend.config import settings as _ss_admin_mfa_cfg
            if getattr(_ss_admin_mfa_cfg, "ss_require_admin_mfa", True):
                if not getattr(u, "totp_enabled", False):
                    raise HTTPException(
                        status_code=403,
                        detail=(
                            "admin role には MFA enrollment が必須です。"
                            "/api/auth/mfa/setup → /api/auth/mfa/confirm で設定してください。"
                        ),
                    )
    except HTTPException:
        raise
    except Exception:
        # DB エラー時は fail-closed (admin は数分待てば良い)
        raise HTTPException(status_code=503, detail="admin re-verification temporarily unavailable")


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
        "\u200b", "\u200c", "\u200d", "\u2028", "\u2029",  # ZWSP/ZWNJ/ZWJ/LS/PS
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",  # LRE/RLE/PDF/LRO/RLO
        "\u2066", "\u2067", "\u2068", "\u2069", "\ufeff",  # LRI/RLI/FSI/PDI/BOM
        "\x7f",  # DEL
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
    # DB 列長 VARCHAR(100) と一致させ、validator 通過後の DB INSERT 500 を防ぐ。
    display_name: str = Field(..., min_length=1, max_length=100)
    username: str = Field(..., min_length=1, max_length=100)
    password: Optional[str] = None
    pin: Optional[str] = None
    player_id: Optional[int] = None
    team_name: Optional[str] = Field(default=None, max_length=100)
    # B-2: 所属チーム指定。team_id 指定（既存チーム）または independent=True（無所属チーム自動生成）
    team_id: Optional[int] = None
    independent: bool = False


class UserUpdate(BaseModel):
    # 未知フィールドを silent drop せず 422 で拒否する。`is_admin` `id` 等の
    # 権限関連を body に混入させる mass assignment 攻撃を検出・遮断する。
    model_config = {"extra": "forbid"}

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    username: Optional[str] = Field(default=None, min_length=1, max_length=100)
    password: Optional[str] = None
    pin: Optional[str] = None
    team_name: Optional[str] = Field(default=None, max_length=100)
    player_id: Optional[int] = None
    # role は admin のみが書換可能。analyst/coach/player が role を送ってきた場合
    # 403 で明示拒否する（silent drop にするとサイレント昇格攻撃を検出困難にする）。
    role: Optional[str] = None
    team_id: Optional[int] = None  # admin のみ変更可
    # is_test: 検証用ユーザ (True=削除可) / 実ユーザ (False=削除保護)。admin のみ変更可。
    is_test: Optional[bool] = None


def _user_to_dict(user: User, db: Session, *, for_admin: bool = False) -> dict:
    player = db.get(Player, user.player_id) if user.player_id else None
    team = db.get(Team, user.team_id) if user.team_id else None
    out = {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
        "team_name": user.team_name,
        "team_id": user.team_id,
        "team_display_name": team.name if team else None,
        "team_is_independent": bool(team.is_independent) if team else None,
        "player_id": user.player_id,
        "player_name": player.name if player else None,
        "has_credential": user.hashed_credential is not None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "mfa_enabled": bool(user.totp_enabled),
        "locked": bool(user.locked_until and user.locked_until > datetime.utcnow()),
        # M-A: メールアドレス + 検証状態 (admin のみ実値、player には返さない)
        "email": getattr(user, "email", None),
        "email_verified": bool(getattr(user, "email_verified_at", None)),
        # M-A 承認待ちフラグ (admin の保留ユーザー一覧で利用)
        "awaiting_admin_approval": bool(getattr(user, "awaiting_admin_approval", False)),
        # 検証用ユーザフラグ (True=削除可 / False=実ユーザで削除保護)。admin UI で表示・切替。
        "is_test": bool(getattr(user, "is_test", False)),
    }
    if for_admin:
        out["team_display_id"] = team.display_id if team else None
    return out


# ── B-2: チーム解決ヘルパ ─────────────────────────────────────────────────────

def _short_uuid_suffix() -> str:
    """無所属チームの display_id 用に 8 文字の短い uuid を返す。"""
    from uuid import uuid4
    return uuid4().hex[:8].upper()


def _resolve_team_for_user_create(
    db: Session,
    *,
    team_id: Optional[int],
    independent: bool,
    team_name: Optional[str] = None,
    display_name_hint: Optional[str] = None,
) -> Team:
    """登録時のチーム解決。

    優先順:
    1. team_id 指定: 既存チームを返す（存在チェック）
    2. team_name 指定: 同名チームがあれば再利用、なければ自動作成
    3. independent=True もしくは team_id/team_name 未指定: 無所属チーム
       （INDEP-xxxx, is_independent=True）を新規作成
    """
    if team_id is not None:
        team = db.get(Team, team_id)
        if not team or team.deleted_at is not None:
            raise HTTPException(status_code=404, detail="指定された team_id が存在しません")
        return team
    # team_name 指定 → 既存チーム lookup or 新規作成
    if team_name and team_name.strip():
        norm = team_name.strip()
        existing = db.query(Team).filter(
            Team.name == norm, Team.deleted_at.is_(None)
        ).first()
        if existing:
            return existing
        # 新規作成（display_id は付けず、admin が後から /teams で付与）
        team = Team(
            uuid=str(_uuid_mod.uuid4()),
            name=norm,
            is_independent=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(team)
        db.flush()
        return team
    # team_id 未指定 → independent=True 扱いで新規作成（互換挙動）
    for _ in range(5):
        display_id = f"INDEP-{_short_uuid_suffix()}"
        existing = db.query(Team).filter(Team.display_id == display_id).first()
        if not existing:
            label = "無所属" if not display_name_hint else f"無所属（{display_name_hint}）"
            team = Team(
                display_id=display_id,
                name=label,
                is_independent=True,
            )
            db.add(team)
            db.flush()
            return team
    raise HTTPException(status_code=500, detail="無所属チーム ID の生成に失敗しました")
    # 旧コード（unreachable）: team_id 由来の解決
    team = db.get(Team, team_id)
    if not team or team.deleted_at is not None:
        raise HTTPException(status_code=404, detail="指定された team_id が存在しません")
    return team


@router.get("/users")
def list_users(request: Request, db: Session = Depends(get_db)):
    from backend.utils.auth import get_auth
    ctx = get_auth(request)

    if ctx.is_admin:
        # Round 281+ meta-audit: admin が全 user 一覧 (username + role + team +
        # display_name + mfa_enabled + page_access) を dump した事実を audit に
        # 記録する。admin token 漏洩時の attacker 一括収集を検出可能にする。
        try:
            log_access(db, "admin_users_listed",
                       user_id=ctx.user_id, ip_addr=_get_ip(request))
        except Exception:
            pass
        users = db.query(User).order_by(User.id).all()
        return {"success": True, "data": [_user_to_dict(u, db, for_admin=True) for u in users]}

    if ctx.is_analyst or ctx.is_coach:
        # analyst も自チームのみ (cross-team 情報漏洩防止)
        team = (ctx.team_name or "").strip()
        if not team:
            # loopback dev/test では admin 同等で全件返す
            from backend.utils.control_plane import allow_legacy_header_auth
            if allow_legacy_header_auth(request):
                users = db.query(User).order_by(User.id).all()
                return {"success": True, "data": [_user_to_dict(u, db, for_admin=True) for u in users]}
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
    allowed_roles = {"admin", "analyst", "coach", "player", "demo", "llm"}
    # role は string の完全一致のみ許可（list/空白混入/enum-bypass を遮断）
    if not isinstance(body.role, str) or body.role not in allowed_roles:
        raise HTTPException(status_code=422, detail=f"invalid role: {body.role!r}")
    # display_name / team_name の制御文字 / BIDI override を拒否
    # DB 列長 (User.display_name VARCHAR(100), team_name VARCHAR(100)) と一致させる。
    # 旧 max_len=120/80 では 101-120 char が DB INSERT で 500 に抜けていた
    # (round 205 V3, round 200 Q6-B 系)。
    _reject_control_chars(body.display_name, "display_name", max_len=100)
    _reject_control_chars(body.team_name, "team_name", max_len=100)
    # display_name 空文字/空白のみ拒否 + HTML タグ拒否 (stored XSS 対策)
    if not body.display_name or not body.display_name.strip():
        raise HTTPException(status_code=422, detail="display_name must not be empty or whitespace only")
    import re as _re_dn
    if _re_dn.search(r"</?(script|iframe|object|embed|svg|style|link|meta|form|img)[\s>/]", body.display_name, _re_dn.IGNORECASE):
        raise HTTPException(status_code=422, detail="display_name contains disallowed HTML tags")
    # analyst は admin / analyst アカウントを作成できない（権限昇格防止）
    if ctx.is_analyst and body.role in ("admin", "analyst", "demo"):
        raise HTTPException(status_code=403, detail="admin/analyst/demo アカウントは admin のみ作成できます")
    # analyst/coach/player は team 必須 (cross-team 漏洩防止)。
    # admin のみ team 未指定を許容（システム横断管理者として扱う）。
    # Phase B-2: team_name もしくは team_id もしくは independent=True で OK。
    if body.role != "admin":
        has_team_name = bool((body.team_name or "").strip())
        has_team_id = body.team_id is not None
        if not (has_team_name or has_team_id or body.independent):
            raise HTTPException(
                status_code=422,
                detail=f"team_name / team_id / independent のいずれかが必要です (role={body.role})",
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

    # B-2: チーム必須化（admin/analyst のみ create するので必ず指定 or independent）
    # team_name を渡せば同名チームを lookup or 自動作成する
    team = _resolve_team_for_user_create(
        db,
        team_id=body.team_id,
        independent=body.independent,
        team_name=body.team_name,
        display_name_hint=body.display_name,
    )

    hashed = _hash_user_credential(body.password, body.pin)
    user = User(
        username=login_id,
        role=body.role,
        display_name=body.display_name,
        team_name=team.name,  # 互換用に表示名を写す
        team_id=team.id,
        player_id=body.player_id,
        hashed_credential=hashed,
    )
    db.add(user)
    # parallel POST race: 同じ username / player_id が DB レベルの unique 制約で
    # IntegrityError になる経路を 409 に正規化する (round 210 AA8)。素の 500 は
    # スタックトレースリークと攻撃者の意図しない情報提示につながるので避ける。
    from sqlalchemy.exc import IntegrityError as _IntegrityError
    try:
        db.commit()
    except _IntegrityError:
        db.rollback()
        # username / player_id どちらの衝突かは error 文面で判別可能だが、
        # 攻撃者向けには曖昧化する (timing / reason side channel 抑制)。
        raise HTTPException(status_code=409, detail="user already exists")
    db.refresh(user)
    log_access(db, "user_created", user_id=user.id, details={"role": body.role, "display_name": body.display_name, "team_id": team.id})
    return {"success": True, "data": {"id": user.id, "role": user.role, "display_name": user.display_name, "team_id": team.id}}


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
    # ── role 書換の権限判定 ──────────────────────────────────────────────
    # admin: 任意。analyst/coach: 自チーム所属ユーザを「自分の権限レベルまで」昇降格可。
    # 制約: 自分自身は不可 / 対象も付与先も自レベル以下 / admin・demo・llm は対象にも
    # 付与先にもできない（昇格経路の遮断: player→admin 等は不可）。player 等は role 変更不可。
    if body.role is not None and not ctx.is_admin:
        if not (ctx.is_analyst or ctx.is_coach):
            raise HTTPException(status_code=403, detail="role の変更権限がありません")
        _ROLE_LEVEL = {"player": 1, "coach": 2, "analyst": 3}
        _op_level = _ROLE_LEVEL[ctx.role]  # analyst=3 / coach=2
        if ctx.user_id == target_id:
            raise HTTPException(status_code=403, detail="自分自身の role は変更できません")
        if ctx.team_id is None or user.team_id != ctx.team_id:
            raise HTTPException(status_code=403, detail="自チームのユーザのみ role を変更できます")
        _cur_level = _ROLE_LEVEL.get(user.role or "")
        if _cur_level is None or _cur_level > _op_level:
            raise HTTPException(status_code=403, detail="このユーザの role は変更できません")
        _new_level = _ROLE_LEVEL.get(body.role)
        if _new_level is None or _new_level > _op_level:
            raise HTTPException(
                status_code=403,
                detail=f"付与できる role は自分の権限 ({ctx.role}) までです",
            )

    # is_test (検証用フラグ) は admin のみ変更可。実ユーザ保護の解除/付与に直結するため。
    if body.is_test is not None and not ctx.is_admin:
        raise HTTPException(
            status_code=403,
            detail="is_test の変更は admin のみ可能です",
        )

    # round174 U2: admin の self role 変更を禁止 (self-demote 不可)。
    # 自分を admin から降格させると system が admin を失う可能性があり、
    # 復旧には DB 直接介入が必要になる。role 変更は別 admin に依頼する運用に限定。
    if body.role is not None and ctx.is_admin and ctx.user_id == target_id:
        raise HTTPException(
            status_code=403,
            detail="admin は自分自身の role を変更できません (別 admin に依頼してください)",
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
        # analyst は自チーム内のユーザーのみ編集可（cross-team IDOR 防止）
        if ctx.user_id != target_id:
            analyst_team = (ctx.team_name or "").strip()
            target_team  = (user.team_name or "").strip()
            if not analyst_team or analyst_team != target_team:
                raise HTTPException(status_code=403, detail="自チームのユーザーのみ編集できます")
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
        # player が権限関連フィールド (username / team_name / team_id / player_id /
        # role) を送ってきたら silent drop ではなく 403 で明示拒否する。
        # silent success は攻撃検出を困難にし、ポリシー意図 (player は自身の表示名や
        # 認証情報のみ自己更新可能) と矛盾する。
        # round180 P6 finding: team_id / role が同 reject 対象に漏れていたため追加。
        # role は事前 admin-only check で 403 になるが、防御深化として明記。
        if any(v is not None for v in (
            body.username, body.team_name, body.team_id,
            body.player_id, body.role,
        )):
            raise HTTPException(
                status_code=403,
                detail="player ロールは username / team / role / player_id を変更できません",
            )
        body = UserUpdate(display_name=body.display_name, password=body.password, pin=body.pin)
    else:
        raise HTTPException(status_code=403, detail="編集権限がありません")

    # Round 258 R22 P1 fix (R22 P1-4): mutation 前に security-sensitive 値の snapshot を
    # 取り、後段で「実際に変わったか」を判定する。
    # 旧 R21 実装は `body.model_dump(exclude_unset=True)` に該当 field が含まれて
    # いれば revoke を発火していたため、no-op (= 同値再送) でも tokens を吹き飛ばし
    # 自己 DoS / log noise / DB 書き込み amp の経路を作っていた。
    _snapshot_role = user.role
    _snapshot_username = user.username
    _snapshot_credential = user.hashed_credential

    # display_name / team_name の制御文字 / BIDI override を拒否
    _reject_control_chars(body.display_name, "display_name", max_len=100)
    _reject_control_chars(body.team_name, "team_name", max_len=100)
    # display_name / team_name HTML タグ拒否 (stored XSS 対策)
    _HTML_TAG_RE = _re.compile(
        r"</?(script|iframe|object|embed|svg|style|link|meta|form|img)[\s>/]",
        _re.IGNORECASE,
    )
    if body.display_name is not None:
        if not body.display_name.strip():
            raise HTTPException(status_code=422, detail="display_name must not be empty or whitespace only")
        if _HTML_TAG_RE.search(body.display_name):
            raise HTTPException(status_code=422, detail="display_name contains disallowed HTML tags")
        user.display_name = body.display_name
    if body.username is not None and (ctx.is_admin or ctx.is_analyst):
        login_id = _validate_login_id(body.username)
        existing = db.query(User).filter(User.username == login_id, User.id != target_id).first()
        if existing:
            raise HTTPException(status_code=409, detail="login_id is already in use")
        user.username = login_id
    # role の適用 (権限判定は上のガードで実施済: admin=任意 / analyst・coach=自チーム・自レベルまで)
    if body.role is not None and (ctx.is_admin or ctx.is_analyst or ctx.is_coach):
        if body.role not in ("admin", "analyst", "coach", "player", "demo", "llm"):
            raise HTTPException(status_code=422, detail=f"invalid role: {body.role}")
        if user.role != body.role:
            _old_role = user.role
            user.role = body.role
            log_access(
                db, "user_role_changed", user_id=ctx.user_id,
                resource_type="user", resource_id=user.id,
                details={"actor_role": ctx.role, "from": _old_role, "to": body.role,
                         "team_id": user.team_id},
            )
    # is_test の切替 (admin のみ、上でガード済)。実ユーザ⇄検証用の付替え。
    if body.is_test is not None and ctx.is_admin:
        user.is_test = bool(body.is_test)
    # team_name / player_id は admin のみ書換可能 (上でガード済)
    # admin が team_name のみ送ってきた場合は teams テーブルで lookup or 自動作成して team_id も更新
    if body.team_name is not None and ctx.is_admin:
        if _HTML_TAG_RE.search(body.team_name):
            raise HTTPException(status_code=422, detail="team_name contains disallowed HTML tags")
        norm = body.team_name.strip()
        if norm and body.team_id is None:
            # 既存チーム lookup
            existing = db.query(Team).filter(
                Team.name == norm, Team.deleted_at.is_(None)
            ).first()
            if existing:
                if user.team_id != existing.id:
                    log_access(
                        db, "user_team_changed", user_id=ctx.user_id,
                        resource_type="user", resource_id=user.id,
                        details={
                            "actor_role": ctx.role,
                            "target_user_id": user.id,
                            "from_team_id": user.team_id,
                            "to_team_id": existing.id,
                            "to_team_name": existing.name,
                            "via": "team_name_lookup",
                        },
                    )
                user.team_id = existing.id
                user.team_name = existing.name
            else:
                # 新規 team 自動作成
                new_team = Team(
                    uuid=str(_uuid_mod.uuid4()),
                    name=norm,
                    is_independent=False,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                db.add(new_team)
                db.flush()
                log_access(
                    db, "user_team_changed", user_id=ctx.user_id,
                    resource_type="user", resource_id=user.id,
                    details={
                        "actor_role": ctx.role,
                        "target_user_id": user.id,
                        "from_team_id": user.team_id,
                        "to_team_id": new_team.id,
                        "to_team_name": new_team.name,
                        "via": "team_name_create",
                    },
                )
                user.team_id = new_team.id
                user.team_name = new_team.name
        else:
            # 互換: team_id 同時送信 or 空文字。下流の team_id 処理に任せる
            user.team_name = body.team_name
    # B-2: team_id 変更は admin のみ。coach/analyst/player は変更不可
    if body.team_id is not None:
        if not ctx.is_admin:
            raise HTTPException(status_code=403, detail="所属チーム（team_id）の変更は admin のみ可能です")
        team = db.get(Team, body.team_id)
        if not team or team.deleted_at is not None:
            raise HTTPException(status_code=404, detail="指定された team_id が存在しません")
        # 監査ログ: team_id 変更（誰が誰のチームをどこからどこへ変えたか）
        prev_team_id = user.team_id
        if prev_team_id != team.id:
            log_access(
                db,
                "user_team_changed",
                user_id=ctx.user_id,
                resource_type="user",
                resource_id=user.id,
                details={
                    "actor_role": ctx.role,
                    "target_user_id": user.id,
                    "from_team_id": prev_team_id,
                    "to_team_id": team.id,
                    "to_team_display_id": team.display_id,
                    "new_team_name": team.name,
                },
            )
        user.team_id = team.id
        user.team_name = team.name
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
    # Round 258 R21 P1 fix (R21 P1-4): role / password / pin / username 変更時には
    # 既存 access token を必ず失効させる。旧 R20 は change_password 系だけだったが、
    # admin が compromised user を demote しても access token は role=admin のまま
    # 残存していた。
    # Round 258 R22 P1 fix (R22 P1-4): 上記 R21 実装は body に field が含まれて
    # **いるだけ** で revoke を発火するため、no-op 再送 (= 同値) でも token を
    # 吹き飛ばす self-DoS / log-noise の経路があった。
    # 修正: snapshot と比較して **実値が変わった場合のみ** 発火する。
    role_changed = (user.role != _snapshot_role)
    username_changed = (user.username != _snapshot_username)
    credential_changed = (user.hashed_credential != _snapshot_credential)
    if role_changed or username_changed or credential_changed:
        from backend.utils.jwt_utils import revoke_all_for_user as _revoke_all_for_user2
        try:
            _revoke_all_for_user2(target_id)
        except Exception as exc:
            logger.error("revoke_all_for_user failed (user_update target=%s): %s", target_id, exc)
            raise HTTPException(status_code=500, detail="access token 失効処理に失敗しました")
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
def delete_user(target_id: int, request: Request, db: Session = Depends(get_db), force: bool = False):
    _require_admin(request)
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if ctx.user_id == target_id:
        raise HTTPException(status_code=400, detail="cannot delete your own user")
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    # 0045: 承認済みの実ユーザ (検証用でなく保留でもない) は誤削除防止。force 無しでは弾く。
    # DB トリガ (migration 0045) が最終防衛線だが、ここで明確な 403 を返す。
    is_protected = (not bool(getattr(user, "is_test", False))) and (
        not bool(getattr(user, "awaiting_admin_approval", False))
    )
    if is_protected and not force:
        raise HTTPException(
            status_code=403,
            detail="保護対象の実ユーザです。削除するには force=1 を指定してください。",
        )
    # round229 A3: User には access_logs / refresh_tokens / shared_sessions /
    # matches.annotator_id / shot_annotations / user_invitations / billing_orders /
    # billing_entitlements 等の FK 子レコードが多数あり、生 db.delete(user) は
    # IntegrityError → 500 になる。各テーブルを user_id=NULL or 削除してから本体を削除。
    #
    # 旧コードの問題:
    #   - "access_log" 単数表記の typo (実テーブルは "access_logs")
    #   - user_invitations.created_by_user_id 列は存在しない (実列は inviter_user_id)
    #   - shared_sessions.created_by_user_id 列は存在しない
    #   - matches.annotator_id / shot_annotations.annotator_user_id / billing_* 系の漏れ
    #   - 各 cleanup 失敗時の db.rollback() が前段の正常 cleanup も巻き戻していた
    #
    # 修正:
    #   - 正しい table / column 名で全 FK 経路を null 化 or 削除
    #   - 各 statement は SAVEPOINT (nested transaction) で囲み、1 つ失敗しても
    #     他は反映する。SQLite では SAVEPOINT も同等に動作する (begin_nested)。
    from sqlalchemy import text as _sa_text
    cleanup_stmts = [
        # round 233 R233-A: access_logs.user_id は migration 0026 で FK を drop 済。
        # 旧コードはここで UPDATE access_logs SET user_id = NULL を実行していたが、
        # canonical bytes が変わって HMAC chain が破損する (verify_chain で
        # first_bad_id 検出される) ため、user 削除時は access_logs を変更しない。
        # orphan integer reference (user_id が指す user 行が消えた状態) は audit log
        # の append-only 原則で許容する。
        # ondelete=CASCADE 持ち (refresh_tokens / revoked_tokens / user_consents /
        # player_page_access) は DB 側で自動削除されるが、明示しておく方が安全。
        ("DELETE FROM refresh_tokens WHERE user_id = :uid", "refresh_tokens"),
        ("DELETE FROM revoked_tokens WHERE user_id = :uid", "revoked_tokens"),
        ("DELETE FROM user_consents WHERE user_id = :uid", "user_consents"),
        ("DELETE FROM player_page_access WHERE user_id = :uid", "player_page_access"),
        # email/password reset tokens
        ("DELETE FROM email_verification_tokens WHERE user_id = :uid", "email_verification_tokens"),
        ("DELETE FROM password_reset_tokens WHERE user_id = :uid", "password_reset_tokens"),
        # user_invitations: 旧コードは存在しない created_by_user_id を使っていた。
        # 正しい列は inviter_user_id (NOT NULL) と consumed_by_user_id (NULL 可)。
        # inviter は招待履歴を残すべきだが NOT NULL のため削除する (trade-off)。
        ("DELETE FROM user_invitations WHERE inviter_user_id = :uid", "user_invitations_inv"),
        ("UPDATE user_invitations SET consumed_by_user_id = NULL WHERE consumed_by_user_id = :uid", "user_invitations_csm"),
        # upload_sessions / server_video_artifacts: NULL 許容なので履歴残し
        ("UPDATE upload_sessions SET user_id = NULL WHERE user_id = :uid", "upload_sessions"),
        ("UPDATE server_video_artifacts SET sender_user_id = NULL WHERE sender_user_id = :uid", "server_video_artifacts"),
        # matches.annotator_id / shot_annotations.annotator_user_id (NULL 許容)
        ("UPDATE matches SET annotator_id = NULL WHERE annotator_id = :uid", "matches_annotator"),
        ("UPDATE shot_annotations SET annotator_user_id = NULL WHERE annotator_user_id = :uid", "shot_annotations"),
        # billing 系 (dormant だが FK は active)
        ("DELETE FROM billing_orders WHERE user_id = :uid", "billing_orders"),
        ("DELETE FROM billing_entitlements WHERE user_id = :uid", "billing_entitlements"),
        ("UPDATE billing_entitlements SET granted_by_user_id = NULL WHERE granted_by_user_id = :uid", "billing_entitlements_granted"),
    ]
    cleanup_log: list[str] = []
    for stmt, label in cleanup_stmts:
        # SAVEPOINT (nested transaction) で囲んで個別失敗を分離する。
        # テーブル / 列が存在しないケースでも他の cleanup を巻き込まず続行。
        try:
            with db.begin_nested():
                result = db.execute(_sa_text(stmt), {"uid": target_id})
                n = getattr(result, "rowcount", 0) or 0
                if n:
                    cleanup_log.append(f"{label}={n}")
        except Exception as exc:
            # nested rollback は外側 transaction を保つので safe
            cleanup_log.append(f"{label}=FAIL({type(exc).__name__})")
    try:
        # 0045: force 削除時は、保護トリガを同一トランザクション内で override する。
        # (SET LOCAL はこの transaction の終了まで有効。PostgreSQL のみ。)
        if force:
            try:
                if db.get_bind().dialect.name == "postgresql":
                    db.execute(_sa_text("SET LOCAL app.allow_protected_delete = 'on'"))
            except Exception:
                pass
        db.execute(_sa_text("DELETE FROM users WHERE id = :uid"), {"uid": target_id})
        db.commit()
    except Exception as exc:
        db.rollback()
        # 詳細は server log に残す。client には generic message を返す。
        import logging as _lg_du
        _lg_du.getLogger(__name__).error(
            "[delete_user] target=%s commit_fail=%s cleanup=%s",
            target_id, exc, cleanup_log,
        )
        raise HTTPException(
            status_code=409,
            detail="ユーザ削除に失敗しました (依存レコードがあります)",
        )
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
    # datetime 型で保持 → UTCJSONResponse が ISO+"Z" にシリアライズ
    created_at: Optional[datetime]


@router.get("/audit-logs")
def list_audit_logs(
    request: Request,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    ip: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """admin のみ。audit (access_logs) を新しい順に最大 limit 件返す。

    Query:
      - action: 完全一致フィルタ (例 "login_failed")
      - user_id: 該当 user_id のみ
      - ip: ip_addr の部分一致 (LIKE %ip%)。プレフィックス (例 "192.168.") や
            完全一致 IP どちらでも使える。`%` `_` は LIKE のメタ文字なので
            エスケープしてから当てる。
      - since: ISO8601 datetime 以降 (created_at >= since)
      - limit: 1..5000 (default 100)
    """
    from backend.db.models import AccessLog
    _require_admin(request)

    # Round 281+ meta-audit: admin による audit log の閲覧自体を audit log に
    # 記録する (self-referential)。admin token が漏洩して attacker が全 user の
    # username + IP を dump した場合、本人が「自分は audit を見ていないのに
    # 閲覧 record が残っている」と気づける手がかりになる。
    try:
        from backend.utils.auth import get_auth as _ga_meta
        _ctx_meta = _ga_meta(request)
        log_access(db, "admin_audit_logs_viewed",
                   user_id=_ctx_meta.user_id, ip_addr=_get_ip(request),
                   details={"filter_action": action, "filter_user_id": user_id,
                            "filter_ip": ip, "filter_since": since,
                            "limit_requested": limit})
    except Exception:
        # meta-audit の失敗で本処理を止めない
        pass

    # 旧 cap 500 だと「件数変更しても 500 件のまま」になりユーザが「動かない」
    # と感じる。admin の audit 用途では数千件まで取得したいケースが普通 (CSV
    # 出力前提)。5000 件まで許容、過大入力は clamp。
    limit = max(1, min(int(limit or 100), 5000))
    q = db.query(AccessLog)
    if action:
        q = q.filter(AccessLog.action == action)
    if user_id is not None:
        q = q.filter(AccessLog.user_id == user_id)
    if ip:
        ip_clean = ip.strip()
        if ip_clean:
            # LIKE メタ文字をエスケープしてから %.. % で囲む
            esc = ip_clean.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q = q.filter(AccessLog.ip_addr.like(f"%{esc}%", escape="\\"))
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
            # backend.main.UTCJSONResponse がグローバルに naive datetime を
            # ISO + "Z" 形式に変換するため、datetime オブジェクトをそのまま渡す
            created_at=r.created_at,
        )
        for r in rows
    ]
    return {"success": True, "data": [e.model_dump() for e in entries]}


@router.get("/audit-logs/request")
def list_request_logs(
    request: Request,
    method: Optional[str] = None,
    path_prefix: Optional[str] = None,
    status_min: Optional[int] = None,
    status_max: Optional[int] = None,
    ip: Optional[str] = None,
    user_id: Optional[int] = None,
    source: Optional[str] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """admin のみ。request_logs を新しい順に最大 limit 件返す。

    Query:
      - method: 'GET' / 'POST' 等の完全一致
      - path_prefix: path LIKE 'prefix%'
      - status_min / status_max: status 範囲 (例 400-599 でエラーのみ)
      - ip: ip_addr の部分一致
      - user_id: 該当 user_id
      - limit: 1..5000 (default 200)
    """
    from backend.db.models import RequestLog
    _require_admin(request)
    limit = max(1, min(int(limit or 200), 5000))
    q = db.query(RequestLog)
    if method:
        q = q.filter(RequestLog.method == method.upper())
    if path_prefix:
        esc = path_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        q = q.filter(RequestLog.path.like(f"{esc}%", escape="\\"))
    if status_min is not None:
        q = q.filter(RequestLog.status >= int(status_min))
    if status_max is not None:
        q = q.filter(RequestLog.status <= int(status_max))
    if ip:
        esc = ip.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        if esc:
            q = q.filter(RequestLog.ip_addr.like(f"%{esc}%", escape="\\"))
    if user_id is not None:
        q = q.filter(RequestLog.user_id == user_id)
    if source:
        q = q.filter(RequestLog.source == source)
    rows = q.order_by(RequestLog.id.desc()).limit(limit).all()
    return {
        "success": True,
        "data": [
            {
                "id": r.id,
                "ts": r.ts,
                "method": r.method,
                "path": r.path,
                "query": r.query,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "user_id": r.user_id,
                "ip_addr": r.ip_addr,
                "xff": r.xff,
                "ua": r.ua,
                "request_id": r.request_id,
                "country": r.country,
                "source": getattr(r, "source", None),
            }
            for r in rows
        ],
    }


@router.get("/audit-logs/security")
def list_security_events(
    request: Request,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    ip: Optional[str] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """admin のみ。security_events を新しい順に返す。

    Query:
      - event_type: probe_attempt / rate_limit_hit / honeytoken_hit 等
      - severity: info / warn / critical
      - ip: ip_addr 部分一致
      - limit: 1..5000 (default 200)
    """
    from backend.db.models import SecurityEvent
    _require_admin(request)
    limit = max(1, min(int(limit or 200), 5000))
    q = db.query(SecurityEvent)
    if event_type:
        q = q.filter(SecurityEvent.event_type == event_type)
    if severity:
        q = q.filter(SecurityEvent.severity == severity)
    if ip:
        esc = ip.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        if esc:
            q = q.filter(SecurityEvent.ip_addr.like(f"%{esc}%", escape="\\"))
    rows = q.order_by(SecurityEvent.id.desc()).limit(limit).all()
    return {
        "success": True,
        "data": [
            {
                "id": r.id,
                "ts": r.ts,
                "event_type": r.event_type,
                "severity": r.severity,
                "ip_addr": r.ip_addr,
                "user_id": r.user_id,
                "path": r.path,
                "method": r.method,
                "ua": r.ua,
                "request_id": r.request_id,
                # details が dict (PG JSONB) でも str (SQLite TEXT) でも文字列で返す
                "details": (
                    __import__("json").dumps(r.details, ensure_ascii=False)
                    if isinstance(r.details, (dict, list))
                    else (r.details or "")
                ),
            }
            for r in rows
        ],
    }


@router.get("/audit-logs/errors")
def list_error_logs(
    request: Request,
    exc_type: Optional[str] = None,
    path_prefix: Optional[str] = None,
    request_id: Optional[str] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """admin のみ。error_logs を新しい順に返す。

    Query:
      - exc_type: 例外クラス名の完全一致 (例 ValueError)
      - path_prefix: path LIKE 'prefix%'
      - request_id: request_logs と相関する request_id
      - limit: 1..2000 (default 200)
    """
    from backend.db.models import ErrorLog
    _require_admin(request)
    limit = max(1, min(int(limit or 200), 2000))
    q = db.query(ErrorLog)
    if exc_type:
        q = q.filter(ErrorLog.exc_type == exc_type)
    if path_prefix:
        esc = path_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        q = q.filter(ErrorLog.path.like(f"{esc}%", escape="\\"))
    if request_id:
        q = q.filter(ErrorLog.request_id == request_id)
    rows = q.order_by(ErrorLog.id.desc()).limit(limit).all()
    return {
        "success": True,
        "data": [
            {
                "id": r.id,
                "ts": r.ts,
                "request_id": r.request_id,
                "method": r.method,
                "path": r.path,
                "status": r.status,
                "exc_type": r.exc_type,
                "message": r.message,
                "traceback": r.traceback,
                "input_repr": r.input_repr,
                "internal_code": r.internal_code,
                "user_id": r.user_id,
                "ip_addr": r.ip_addr,
            }
            for r in rows
        ],
    }


@router.get("/audit-logs/actions")
def list_audit_log_actions(request: Request, db: Session = Depends(get_db)):
    """admin のみ。access_logs に出現する distinct な action 名一覧 (件数付き)。
    フロント側で action filter を dropdown 化するために使う。"""
    from backend.db.models import AccessLog
    from sqlalchemy import func
    _require_admin(request)
    rows = (
        db.query(AccessLog.action, func.count(AccessLog.id))
        .group_by(AccessLog.action)
        .order_by(func.count(AccessLog.id).desc())
        .limit(500)
        .all()
    )
    return {
        "success": True,
        "data": [{"action": a, "count": int(c)} for a, c in rows if a],
    }


@router.get("/audit-logs/verify")
def verify_audit_logs(
    request: Request,
    from_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """admin のみ。access_logs のハッシュチェーン整合性を返す。

    Round 233 R233-A: 過去の delete_user 修正バグで chain が一度破損している
    (first_bad_id=466 付近)。migration 0026 + delete_user 修正以降は新規 row が
    valid な chain を維持するため、admin は `?from_id=<break_id+1>` で破損
    segment 以降を検証できる。
    """
    _require_admin(request)
    from backend.utils.access_log import verify_chain
    result = verify_chain(db, from_id=from_id)
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
    from backend.utils.auth import get_auth
    _require_manager(request)
    ctx = get_auth(request)
    user = db.get(User, target_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    # round 245 R245-E7: cross-team page-access leak 防止。
    # admin 以外は同 team の player にのみ参照可能。
    if not ctx.is_admin:
        if user.team_id is None or ctx.team_id is None or user.team_id != ctx.team_id:
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
    # round 245 R245-E7: 旧コードは _require_manager (admin/analyst/coach) のみで
    # cross-team scope check が無く、analyst (team A) が player (team B) の page_access
    # を全削除できた。admin 以外は対象 player と同 team_id でのみ操作可能にする。
    # 404 で返すのは存在 leak (404 vs 403 の区別) を避けるため。
    if not ctx.is_admin:
        if user.team_id is None or ctx.team_id is None or user.team_id != ctx.team_id:
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
    from backend.utils.auth import get_auth
    _require_manager(request)
    ctx = get_auth(request)
    # round 245 R245-E7 系: cross-team page-access leak 防止。
    if not ctx.is_admin:
        actor_team = (ctx.team_name or "").strip()
        if not actor_team or actor_team != team_name:
            raise HTTPException(status_code=404, detail="team not found")
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
    # round 245 R245-E7 系: team-level page-access も同じ cross-team 問題。
    # admin 以外は自身の team_name にのみ操作可能。
    if not ctx.is_admin:
        actor_team = (ctx.team_name or "").strip()
        if not actor_team or actor_team != team_name:
            raise HTTPException(status_code=404, detail="team not found")
    valid = {k for k in body.page_keys if k in GRANTABLE_PAGES}
    db.query(PlayerPageAccess).filter(
        PlayerPageAccess.team_name == team_name,
        PlayerPageAccess.user_id.is_(None),
    ).delete()
    for key in valid:
        db.add(PlayerPageAccess(page_key=key, team_name=team_name, granted_by_user_id=ctx.user_id))
    db.commit()
    return {"success": True, "data": list(valid)}


# ── B-2: チーム管理（teams テーブル CRUD） ───────────────────────────────────

class TeamBody(BaseModel):
    # mass assignment 防御: 内部フィールド (uuid/created_at/deleted_at 等) を body 経由
    # で上書きさせない。長さ制約は DB 列長と整合させる (Team.name VARCHAR(100), short_name 50)。
    model_config = {"extra": "forbid"}
    name: str = Field(..., min_length=1, max_length=100)
    display_id: Optional[str] = Field(default=None, max_length=64)
    short_name: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=5000)
    is_independent: bool = False


class TeamPatch(BaseModel):
    model_config = {"extra": "forbid"}
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    display_id: Optional[str] = Field(default=None, max_length=64)
    short_name: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=5000)


def _team_to_dict(team: Team, *, for_admin: bool = False) -> dict:
    """チーム情報を dict 化する。

    display_id / notes は内部運用情報のため admin 限定で開示する。
    coach / analyst / player には UI 表示用の name のみ返す。
    """
    base = {
        "id": team.id,
        "uuid": team.uuid,
        "name": team.name,
        "short_name": team.short_name,
        "is_independent": bool(team.is_independent),
        "created_at": team.created_at.isoformat() if team.created_at else None,
        "updated_at": team.updated_at.isoformat() if team.updated_at else None,
    }
    if for_admin:
        base["display_id"] = team.display_id
        base["notes"] = team.notes
    return base


@router.get("/teams")
def list_teams(request: Request, db: Session = Depends(get_db)):
    """チーム一覧。

    - admin: 全チーム閲覧可
    - coach/analyst/player: 自チームのみ閲覧可（リーク防止）
    """
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    q = db.query(Team).filter(Team.deleted_at.is_(None))
    if ctx.is_admin:
        teams = q.order_by(Team.id).all()
    else:
        if ctx.team_id is None:
            return {"success": True, "data": []}
        teams = q.filter(Team.id == ctx.team_id).all()
    return {"success": True, "data": [_team_to_dict(t, for_admin=ctx.is_admin) for t in teams]}


@router.post("/teams", status_code=201)
def create_team(body: TeamBody, request: Request, db: Session = Depends(get_db)):
    """チームを新規作成。admin のみ可。"""
    _require_admin(request)
    # DB 列長 (Team.name VARCHAR(100), short_name VARCHAR(50), display_id VARCHAR(64))
    # に整合させた上で、BIDI override / 制御文字 (CRLF・null byte 含む) を拒否。
    # 旧コードはここでバリデートしておらず Team.name BIDI 通過 + 101 char 500 が発生
    # していた (round 200 Q6-A / Q6-B)。
    _reject_control_chars(body.name, "name", max_len=100)
    _reject_control_chars(body.short_name, "short_name", max_len=50)
    _reject_control_chars(body.display_id, "display_id", max_len=64)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    display_id = (body.display_id or "").strip() or None
    if display_id:
        existing = db.query(Team).filter(Team.display_id == display_id).first()
        if existing:
            raise HTTPException(status_code=409, detail="display_id is already in use")
    team = Team(
        name=name,
        display_id=display_id,
        short_name=(body.short_name or None),
        notes=(body.notes or None),
        is_independent=bool(body.is_independent),
    )
    db.add(team)
    # parallel POST race: 同じ display_id が DB unique 制約で IntegrityError →
    # 旧コードは 500 にリーク。round 211 BB2 で確認した経路を 409 に正規化する
    # (POST /api/auth/users の round 210 AA8 と同パターン)。
    from sqlalchemy.exc import IntegrityError as _IntegrityError
    try:
        db.commit()
    except _IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="team already exists")
    db.refresh(team)
    log_access(db, "team_created", details={"team_id": team.id, "display_id": team.display_id})
    return {"success": True, "data": _team_to_dict(team, for_admin=True)}


@router.patch("/teams/{team_id}")
def patch_team(team_id: int, body: TeamPatch, request: Request, db: Session = Depends(get_db)):
    """チーム情報を更新。

    - admin: 全チーム編集可
    - coach: 自チームのみ編集可（display_id, name, short_name, notes）
    - その他: 不可
    """
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    team = db.get(Team, team_id)
    if not team or team.deleted_at is not None:
        raise HTTPException(status_code=404, detail="team not found")
    if ctx.is_admin:
        pass
    elif ctx.is_coach and ctx.team_id == team_id:
        pass
    else:
        raise HTTPException(status_code=403, detail="チーム編集の権限がありません")
    # PATCH も BIDI/制御文字/長大値を統一拒否 (round 203 T7 で短縮通過した経路の修正)。
    _reject_control_chars(body.name, "name", max_len=100)
    _reject_control_chars(body.short_name, "short_name", max_len=50)
    _reject_control_chars(body.display_id, "display_id", max_len=64)
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="name は空にできません")
        team.name = name
    if body.display_id is not None:
        # display_id は内部運用情報なので admin のみ変更可
        if not ctx.is_admin:
            raise HTTPException(status_code=403, detail="display_id の変更は admin のみ可能です")
        new_display = body.display_id.strip() or None
        if new_display and new_display != team.display_id:
            dup = db.query(Team).filter(Team.display_id == new_display, Team.id != team_id).first()
            if dup:
                raise HTTPException(status_code=409, detail="display_id is already in use")
        team.display_id = new_display
    if body.short_name is not None:
        team.short_name = body.short_name.strip() or None
    if body.notes is not None:
        team.notes = body.notes or None
    db.commit()
    log_access(db, "team_updated", details={"team_id": team.id})
    return {"success": True, "data": _team_to_dict(team, for_admin=ctx.is_admin)}


# ─── チーム削除 (Round 258 #16: admin による soft-delete) ──────────────────

def _team_dep_counts(db: Session, team_id: int) -> dict[str, int]:
    """チーム削除前の依存カウント。

    soft-deleted (deleted_at IS NOT NULL) の行は除外し、現役ぶら下がりだけを数える。
    """
    from backend.db.models import Match, User
    counts: dict[str, int] = {}
    counts["users"] = (
        db.query(User).filter(User.team_id == team_id).count()
    )
    counts["players"] = (
        db.query(Player).filter(
            Player.team_id == team_id,
            Player.deleted_at.is_(None),
        ).count()
    )
    counts["matches"] = (
        db.query(Match).filter(
            (
                (Match.owner_team_id == team_id)
                | (Match.home_team_id == team_id)
                | (Match.away_team_id == team_id)
            ),
            Match.deleted_at.is_(None),
        ).count()
    )
    return counts


@router.get("/teams/{team_id}/dependencies")
def get_team_dependencies(team_id: int, request: Request, db: Session = Depends(get_db)):
    """admin のみ。チームに紐付く現役レコード数を返す。削除確認 UI 用。"""
    _require_admin(request)
    team = db.get(Team, team_id)
    if not team or team.deleted_at is not None:
        raise HTTPException(status_code=404, detail="team not found")
    return {
        "success": True,
        "data": {
            "team_id": team.id,
            "team_name": team.name,
            "counts": _team_dep_counts(db, team_id),
        },
    }


@router.delete("/teams/{team_id}")
def delete_team(
    team_id: int,
    request: Request,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """admin のみ。チームを soft-delete する。

    依存解決:
    - force=false (既定): 現役 user / player / match が紐付いている場合は 409 で
      返却。レスポンスに依存カウントを含めるので UI で確認後 force=true で再要求。
    - force=true: 紐付いている User.team_id / Player.team_id /
      Match.owner_team_id / home_team_id / away_team_id を NULL にして孤児化させ
      (orphan)、そのうえで Team.deleted_at を設定する。
      孤児化された User/Player は admin が手動で再割当する想定。

    注意:
    - 物理削除はしない (audit chain / 過去ラリー参照保全のため)。
    - Round 233 で確認済みの DPAPI / FK 設計と矛盾なし。
    """
    _require_admin(request)
    from backend.utils.auth import get_auth as _ga_del
    ctx = _ga_del(request)
    # Round 258 P1 fix: TOCTOU + 並列 DELETE 重複監査ログ問題の対策。
    # team 行を SELECT FOR UPDATE で排他ロックし、トランザクション中に
    # 他リクエストが同 team を編集できないようにする。
    # SQLite は SELECT FOR UPDATE を無視するが、PostgreSQL では正しく機能する。
    team = (
        db.query(Team)
        .filter(Team.id == team_id)
        .with_for_update()
        .one_or_none()
    )
    if not team or team.deleted_at is not None:
        # 既に他のリクエストが soft-delete 済 → 404 を返し重複監査ログを防ぐ
        raise HTTPException(status_code=404, detail="team not found")

    counts = _team_dep_counts(db, team_id)
    if not force and (counts["users"] or counts["players"] or counts["matches"]):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "team_has_dependencies",
                "counts": counts,
                "hint": "force=true を指定すると依存レコードを孤児化 (team_id=NULL) してから削除します",
            },
        )

    # force 時の孤児化
    orphaned = {"users": 0, "players": 0, "matches": 0}
    if force:
        from backend.db.models import Match, User
        # User.team_id NULL 化 (User.team_name 文字列は履歴のため残す)
        for u in db.query(User).filter(User.team_id == team_id).all():
            u.team_id = None
            orphaned["users"] += 1
        for p in (
            db.query(Player)
            .filter(Player.team_id == team_id, Player.deleted_at.is_(None))
            .all()
        ):
            p.team_id = None
            orphaned["players"] += 1
        for m in (
            db.query(Match)
            .filter(
                (
                    (Match.owner_team_id == team_id)
                    | (Match.home_team_id == team_id)
                    | (Match.away_team_id == team_id)
                ),
                Match.deleted_at.is_(None),
            )
            .all()
        ):
            if m.owner_team_id == team_id:
                m.owner_team_id = None
            if m.home_team_id == team_id:
                m.home_team_id = None
            if m.away_team_id == team_id:
                m.away_team_id = None
            orphaned["matches"] += 1

        # Round 258 P1 fix: TOCTOU 二段目 — orphan ループ実行中に並行 POST /api/players
        # で同 team_id の新しい player が insert される可能性がある。
        # team.deleted_at セット直前に再カウントして、孤児化漏れがあれば例外を上げて
        # トランザクションをロールバックさせ、リトライを促す (再 SELECT FOR UPDATE で
        # 並行 player insert を見せる)。
        recount = _team_dep_counts(db, team_id)
        if recount["users"] or recount["players"] or recount["matches"]:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "team_dependencies_changed_during_delete",
                    "counts": recount,
                    "hint": "並行作業で新しい依存レコードが追加されました。再試行してください",
                },
            )

    team.deleted_at = datetime.utcnow()
    db.commit()

    # 監査ログ (誰がどの team を force/soft delete したか forensic 用)
    log_access(
        db,
        "team_deleted",
        details={
            "team_id": team_id,
            "team_name": team.name,
            "force": force,
            "orphaned": orphaned,
            "actor_user_id": ctx.user_id,
        },
    )

    return {
        "success": True,
        "data": {
            "team_id": team_id,
            "deleted_at": team.deleted_at.isoformat() + "Z" if team.deleted_at else None,
            "force": force,
            "orphaned": orphaned,
        },
    }


# ─── 同意取得 (GDPR Article 7 / APPI 第18条) ───────────────────────────────

# 現行 PRIVACY.md / TERMS_OF_SERVICE.md / DATA_CONTRIBUTION_TERMS.md の version。
# 文書改定時はここを更新し、frontend 側にも反映する (再同意取得の判定根拠)。
# 2026-05-08: PRIVACY v1.2 (Article IX §9.3 追加) / TERMS v1.2 (§16/§17 追加) で更新。
# 2026-05-18: TERMS v1.3 (§9 を SLA 免責 + 不可抗力 + 個人運営の透明開示で大幅拡張)。
# 2026-05-19: PRIVACY v1.3 (Article IX-bis テレメトリ + IX-ter 未成年配慮 を追加)。
CURRENT_PRIVACY_VERSION = "1.3"
CURRENT_TERMS_VERSION = "1.3"
CURRENT_DCT_VERSION = "1.0"

# ユーザが同意可能な目的。各 type は独立して give/withdraw 可能 (GDPR Article 7(2))。
# service_delivery のみ必須 (これに同意しない限り Service 提供不可)、他は opt-in。
_REQUIRED_CONSENT_TYPES = {"service_delivery", "beta_agreement"}
_OPTIONAL_CONSENT_TYPES = {
    "ai_training",
    "research_participation",
    "cross_border_transfer",
    # 同意書 第5条 アライメント: 体組成 (Tier 3) は通常 admin / 本人のみ。
    # player が明示的に "analyst / coach に開示" 同意を ON にすると、
    # それぞれのロールが Tier 3 まで閲覧可になる。default は OFF。
    "body_disclose_to_analyst",
    "body_disclose_to_coach",
}
_ALL_CONSENT_TYPES = _REQUIRED_CONSENT_TYPES | _OPTIONAL_CONSENT_TYPES


def _hash_user_agent(ua: Optional[str]) -> Optional[str]:
    """User-Agent を SHA256 hash 化 (raw UA は保存せず PII 縮減)。"""
    if not ua:
        return None
    import hashlib as _h
    return _h.sha256(ua.encode("utf-8", errors="replace")).hexdigest()[:64]


def _client_ip(request: Request) -> Optional[str]:
    """クライアント IP を取得。Round 258 R3 fix: loopback (cloudflared) 経由のときのみ
    CF-Connecting-IP / X-Forwarded-For を信用する (utils.client_ip 統一)。"""
    from backend.utils.client_ip import trusted_client_ip
    ip = trusted_client_ip(request, default="")
    return ip[:64] if ip else None


class ConsentItem(BaseModel):
    """同意 1 項目。consent_given は StrictBool を採用し、"yes"/"1" 等の string
    から bool への暗黙 coerce を禁止する (Article 7 unambiguous 要件への対応)。"""
    model_config = {"extra": "forbid"}

    consent_type: str
    consent_given: StrictBool


class ConsentSubmitBody(BaseModel):
    """4 種同意 + β合意書同意を一括送信する。

    POST /api/auth/consents
    body = {"consents": [{consent_type, consent_given}, ...],
            "privacy_policy_version": "...",
            "terms_version": "..."}
    """
    model_config = {"extra": "forbid"}

    consents: list[ConsentItem]
    privacy_policy_version: str
    terms_version: str


@router.get("/consents")
def get_my_consents(request: Request, db: Session = Depends(get_db)):
    """自分の同意状態 (最新 give / withdraw) を返す。"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")

    rows = (
        db.query(UserConsent)
        .filter(UserConsent.user_id == ctx.user_id)
        .order_by(UserConsent.given_at.desc())
        .all()
    )
    # type ごとに最新 1 件 (give または withdraw)
    latest: dict[str, dict] = {}
    for r in rows:
        t = r.consent_type
        if t in latest:
            continue
        latest[t] = {
            "consent_type": t,
            "consent_given": bool(r.consent_given) and r.withdrawn_at is None,
            "privacy_policy_version": r.privacy_policy_version,
            "terms_version": r.terms_version,
            "given_at": r.given_at.isoformat() if r.given_at else None,
            "withdrawn_at": r.withdrawn_at.isoformat() if r.withdrawn_at else None,
        }
    user = db.get(User, ctx.user_id)
    # PRIVACY §9ter: 未成年判定 (date_of_birth が分かる場合のみ)
    viewer_is_minor = False
    try:
        if user and getattr(user, "date_of_birth", None):
            from datetime import date as _date
            today = _date.today()
            age = today.year - user.date_of_birth.year - (
                (today.month, today.day) < (user.date_of_birth.month, user.date_of_birth.day)
            )
            viewer_is_minor = age < 18
    except Exception:
        viewer_is_minor = False
    # role='llm' (汎用 LLM チャット専用) は badminton 固有の任意同意 (体組成開示 /
    # AI 学習 / 学術研究 / 越境移転) を一切持たない。カタログからも撤回 UI からも除外し、
    # 既に記録があっても表示しない。必須同意 (service_delivery / beta_agreement) は汎用
    # なので残す。
    _is_llm_only = (getattr(ctx, "role", None) == "llm")
    _shown_optional = set() if _is_llm_only else _OPTIONAL_CONSENT_TYPES
    _shown_consents = [
        c for c in latest.values()
        if not (_is_llm_only and c["consent_type"] in _OPTIONAL_CONSENT_TYPES)
    ]
    return {
        "success": True,
        "data": {
            "consent_required": bool(user.consent_required) if user else True,
            "current_versions": {
                "privacy_policy": CURRENT_PRIVACY_VERSION,
                "terms": CURRENT_TERMS_VERSION,
                "data_contribution": CURRENT_DCT_VERSION,
            },
            "required_types": sorted(_REQUIRED_CONSENT_TYPES),
            "optional_types": sorted(_shown_optional),
            "consents": _shown_consents,
            "viewer_is_minor": viewer_is_minor,
        },
    }


@router.post("/consents", status_code=201)
def submit_consents(
    body: ConsentSubmitBody, request: Request, db: Session = Depends(get_db)
):
    """同意項目を一括登録する (初回同意 / 文書改定後の再同意 / 個別更新を兼ねる)。

    GDPR Article 7(1) (demonstrate consent) 準拠で privacy_policy_version /
    terms_version / given_at / IP / UA hash を残す。同 consent_type に対する
    新規行を append し、過去の give/withdraw 履歴は保持する (audit 用)。
    """
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")

    # version 妥当性
    if body.privacy_policy_version != CURRENT_PRIVACY_VERSION:
        raise HTTPException(
            status_code=409,
            detail=(
                f"プライバシーポリシーが更新されています "
                f"(送信: {body.privacy_policy_version}, 現行: {CURRENT_PRIVACY_VERSION})。"
                f"再読込してから同意してください。"
            ),
        )
    if body.terms_version != CURRENT_TERMS_VERSION:
        raise HTTPException(
            status_code=409,
            detail=(
                f"利用規約が更新されています "
                f"(送信: {body.terms_version}, 現行: {CURRENT_TERMS_VERSION})。"
                f"再読込してから同意してください。"
            ),
        )

    # 必須同意の検証
    given_types = {c.consent_type: c.consent_given for c in body.consents}
    for t in given_types:
        if t not in _ALL_CONSENT_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"未知の consent_type: {t!r}",
            )
    # 必須同意は **初回 (= consent_required=True) のみ** 全項目を要求する。
    # 既に onboarding 済みのユーザが optional consent (body_disclose_to_* 等) を
    # 個別に on/off する場合は partial submit を許可する。
    # こうしないと「同意撤回 → 再同意」が partial submit になり 422 で蹴られていた。
    user_initial = db.get(User, ctx.user_id)
    is_initial_consent = bool(user_initial.consent_required) if user_initial else True
    if is_initial_consent:
        for required in _REQUIRED_CONSENT_TYPES:
            if not given_types.get(required, False):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"必須同意 ({required}) が未取得です。Service 提供のため "
                        f"以下の同意が必要です: {sorted(_REQUIRED_CONSENT_TYPES)}"
                    ),
                )

    ip = _client_ip(request)
    ua = _hash_user_agent(request.headers.get("user-agent"))
    now = datetime.utcnow()

    for item in body.consents:
        rec = UserConsent(
            user_id=ctx.user_id,
            consent_type=item.consent_type,
            consent_given=bool(item.consent_given),
            privacy_policy_version=body.privacy_policy_version,
            terms_version=body.terms_version,
            given_at=now,
            withdrawn_at=None if item.consent_given else now,
            ip_address=ip,
            user_agent_hash=ua,
        )
        db.add(rec)

    # 必須同意が取得できたので consent_required フラグを下ろす
    user = db.get(User, ctx.user_id)
    if user is not None:
        user.consent_required = False

    db.commit()
    log_access(
        db,
        "consents_submitted",
        details={
            "consent_types": sorted(given_types.keys()),
            "privacy_policy_version": body.privacy_policy_version,
            "terms_version": body.terms_version,
        },
    )
    return {"success": True, "data": {"consent_required": False}}


@router.delete("/consents/{consent_type}")
def withdraw_consent(consent_type: str, request: Request, db: Session = Depends(get_db)):
    """指定 consent_type の同意を撤回する (GDPR Article 7(3) 準拠)。

    必須同意 (service_delivery / beta_agreement) は撤回不可。撤回したい場合は
    アカウント削除を先に行う運用とする (Service 提供不能になるため)。
    """
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.user_id:
        raise HTTPException(status_code=401, detail="認証が必要です")

    if consent_type not in _ALL_CONSENT_TYPES:
        raise HTTPException(status_code=422, detail=f"未知の consent_type: {consent_type!r}")
    if consent_type in _REQUIRED_CONSENT_TYPES:
        raise HTTPException(
            status_code=403,
            detail=(
                f"必須同意 ({consent_type}) は撤回できません。"
                f"撤回する場合はアカウント削除を依頼してください "
                f"(Service 提供のため必須項目)。"
            ),
        )

    now = datetime.utcnow()
    rec = UserConsent(
        user_id=ctx.user_id,
        consent_type=consent_type,
        consent_given=False,
        privacy_policy_version=CURRENT_PRIVACY_VERSION,
        terms_version=CURRENT_TERMS_VERSION,
        given_at=now,
        withdrawn_at=now,
        ip_address=_client_ip(request),
        user_agent_hash=_hash_user_agent(request.headers.get("user-agent")),
    )
    db.add(rec)
    db.commit()
    log_access(db, "consent_withdrawn", details={"consent_type": consent_type})
    return {"success": True, "data": {"consent_type": consent_type, "withdrawn_at": now.isoformat()}}
