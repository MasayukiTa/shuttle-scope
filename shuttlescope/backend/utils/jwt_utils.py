"""JWT トークン生成・検証・失効ユーティリティ"""
import hashlib
import secrets
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from backend.config import settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
# Phase B-1: access token を短命化し refresh token で再取得する
ACCESS_TOKEN_EXPIRE_MINUTES = 15
ADMIN_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7


def create_access_token(
    user_id: int,
    role: str,
    player_id: Optional[int] = None,
    team_name: Optional[str] = None,
    hours: Optional[float] = None,
    minutes: Optional[float] = None,
) -> str:
    if minutes is not None:
        delta = timedelta(minutes=minutes)
    elif hours is not None:
        delta = timedelta(hours=hours)
    else:
        m = ADMIN_TOKEN_EXPIRE_MINUTES if role == "admin" else ACCESS_TOKEN_EXPIRE_MINUTES
        delta = timedelta(minutes=m)
    expire = datetime.utcnow() + delta
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": str(uuid.uuid4()),
    }
    if player_id is not None:
        payload["player_id"] = player_id
    if team_name:
        payload["team_name"] = team_name
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """refresh token 本体 (平文) / jti / expires_at を返す。

    DB 保存は呼び出し側が `token_hash = _hash_refresh_token(token)` で行う。
    本関数は DB 書き込みを行わない（呼び出し側でトランザクション制御するため）。
    """
    jti = str(uuid.uuid4())
    raw = secrets.token_urlsafe(48)
    expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return raw, jti, expires_at


def persist_refresh_token(user_id: int, token: str, jti: str, expires_at: datetime) -> None:
    """refresh token の hash 値を DB に保存する。"""
    from backend.db.database import SessionLocal
    from backend.db.models import RefreshToken
    try:
        with SessionLocal() as db:
            db.add(RefreshToken(
                jti=jti,
                user_id=user_id,
                token_hash=_hash_refresh_token(token),
                expires_at=expires_at,
            ))
            db.commit()
    except Exception as exc:
        logger.warning("persist_refresh_token failed user_id=%s: %s", user_id, exc)
        raise


def rotate_refresh_token(presented_token: str) -> Optional[dict]:
    """提示された refresh token を検証し、rotation 方式で新 refresh を発行する。

    返却: {"user_id": int, "new_token": str, "new_jti": str, "new_expires_at": datetime}
          無効・失効・reuse 検知時は None。

    reuse detection: 既に revoked_at が入っている行が一致した場合、同 user の
    全 refresh token を revoke する（漏洩の可能性が高い）。
    """
    from backend.db.database import SessionLocal
    from backend.db.models import RefreshToken
    presented_hash = _hash_refresh_token(presented_token)
    try:
        with SessionLocal() as db:
            row = (
                db.query(RefreshToken)
                .filter(RefreshToken.token_hash == presented_hash)
                .first()
            )
            if row is None:
                return None
            now = datetime.utcnow()
            if row.expires_at <= now:
                return None
            if row.revoked_at is not None:
                # reuse 検知: chain 全体を revoke
                (
                    db.query(RefreshToken)
                    .filter(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
                    .update({"revoked_at": now}, synchronize_session=False)
                )
                db.commit()
                logger.warning("refresh token reuse detected user_id=%s, revoked chain", row.user_id)
                return None

            # rotation: 新しい refresh を発行して旧 refresh を revoke
            new_raw, new_jti, new_exp = create_refresh_token(row.user_id)
            db.add(RefreshToken(
                jti=new_jti,
                user_id=row.user_id,
                token_hash=_hash_refresh_token(new_raw),
                expires_at=new_exp,
            ))
            row.revoked_at = now
            row.replaced_by_jti = new_jti
            db.commit()
            return {
                "user_id": row.user_id,
                "new_token": new_raw,
                "new_jti": new_jti,
                "new_expires_at": new_exp,
            }
    except Exception as exc:
        logger.warning("rotate_refresh_token failed: %s", exc)
        return None


def revoke_refresh_token_by_plain(presented_token: str) -> bool:
    """平文 refresh token を受け取り、該当行を revoke する（logout 時に使用）。"""
    from backend.db.database import SessionLocal
    from backend.db.models import RefreshToken
    presented_hash = _hash_refresh_token(presented_token)
    try:
        with SessionLocal() as db:
            row = (
                db.query(RefreshToken)
                .filter(RefreshToken.token_hash == presented_hash)
                .first()
            )
            if row is None:
                return False
            if row.revoked_at is None:
                row.revoked_at = datetime.utcnow()
                db.commit()
            return True
    except Exception as exc:
        logger.warning("revoke_refresh_token_by_plain failed: %s", exc)
        return False


def revoke_all_refresh_tokens_for_user(user_id: int) -> int:
    """ユーザーの未失効 refresh token を全て revoke する。"""
    from backend.db.database import SessionLocal
    from backend.db.models import RefreshToken
    try:
        with SessionLocal() as db:
            now = datetime.utcnow()
            count = (
                db.query(RefreshToken)
                .filter(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
                .update({"revoked_at": now}, synchronize_session=False)
            )
            db.commit()
            return int(count or 0)
    except Exception as exc:
        logger.warning("revoke_all_refresh_tokens_for_user failed user_id=%s: %s", user_id, exc)
        return 0


def verify_token(token: str) -> Optional[dict]:
    """トークンを検証してペイロードを返す。無効・失効済みの場合は None。

    APT 対策として以下の追加検証を行う:
    - iat が未来 (時計ずれ > 5 分) の JWT は拒否（偽造時計攻撃）
    - iat と exp の差が想定有効期間を超える JWT は拒否（forge した超長寿命 JWT 対策）
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        jti = payload.get("jti")
        if jti and _is_token_revoked(jti):
            logger.debug("JWT rejected: token has been revoked jti=%s", jti)
            return None

        # iat sanity check (5 分の時計ずれのみ許容)
        import time as _time
        now = int(_time.time())
        iat = payload.get("iat")
        if iat is not None:
            try:
                iat_i = int(iat)
                if iat_i > now + 300:
                    logger.warning("JWT rejected: iat in future iat=%s now=%s", iat_i, now)
                    return None
                # exp - iat が想定有効期限（24時間 = 86400秒）を大幅超過していれば拒否
                exp = payload.get("exp")
                if exp is not None:
                    try:
                        exp_i = int(exp)
                        if exp_i - iat_i > 86400 * 2:
                            logger.warning("JWT rejected: exp-iat too long exp=%s iat=%s", exp_i, iat_i)
                            return None
                    except (ValueError, TypeError):
                        pass
            except (ValueError, TypeError):
                return None

        return payload
    except JWTError as e:
        logger.debug("JWT verification failed: %s", e)
        return None


def revoke_token(jti: str, user_id: Optional[int], expires_at: datetime) -> None:
    """JTIをブラックリストに登録する（ログアウト時に呼ぶ）。"""
    from backend.db.database import SessionLocal
    from backend.db.models import RevokedToken
    try:
        with SessionLocal() as db:
            db.add(RevokedToken(jti=jti, user_id=user_id, expires_at=expires_at))
            db.commit()
    except Exception as exc:
        logger.warning("Failed to revoke token jti=%s: %s", jti, exc)


def _is_token_revoked(jti: str) -> bool:
    """ブラックリストにJTIが存在するか確認する。"""
    from backend.db.database import SessionLocal
    from backend.db.models import RevokedToken
    try:
        with SessionLocal() as db:
            return (
                db.query(RevokedToken)
                .filter(
                    RevokedToken.jti == jti,
                    RevokedToken.expires_at > datetime.utcnow(),
                )
                .first()
            ) is not None
    except Exception as exc:
        logger.warning("Blacklist check failed jti=%s: %s", jti, exc)
        return False


def cleanup_expired_revoked_tokens() -> int:
    """有効期限切れのブラックリストエントリを削除して件数を返す。起動時に呼ぶ。"""
    from backend.db.database import SessionLocal
    from backend.db.models import RevokedToken
    try:
        with SessionLocal() as db:
            deleted = (
                db.query(RevokedToken)
                .filter(RevokedToken.expires_at <= datetime.utcnow())
                .delete()
            )
            db.commit()
            return deleted
    except Exception as exc:
        logger.warning("cleanup_expired_revoked_tokens failed: %s", exc)
        return 0
