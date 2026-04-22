"""JWT トークン生成・検証・失効ユーティリティ"""
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from backend.config import settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8
ADMIN_TOKEN_EXPIRE_HOURS = 24


def create_access_token(
    user_id: int,
    role: str,
    player_id: Optional[int] = None,
    team_name: Optional[str] = None,
    hours: Optional[float] = None,
) -> str:
    if hours is None:
        hours = ADMIN_TOKEN_EXPIRE_HOURS if role == "admin" else ACCESS_TOKEN_EXPIRE_HOURS
    expire = datetime.utcnow() + timedelta(hours=hours)
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


def verify_token(token: str) -> Optional[dict]:
    """トークンを検証してペイロードを返す。無効・失効済みの場合は None。"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        jti = payload.get("jti")
        if jti and _is_token_revoked(jti):
            logger.debug("JWT rejected: token has been revoked jti=%s", jti)
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
