"""JWT トークン生成・検証ユーティリティ"""
from datetime import datetime, timedelta
from typing import Optional
import logging

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
    hours: Optional[int] = None,
) -> str:
    if hours is None:
        hours = ADMIN_TOKEN_EXPIRE_HOURS if role == "admin" else ACCESS_TOKEN_EXPIRE_HOURS
    expire = datetime.utcnow() + timedelta(hours=hours)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    if player_id is not None:
        payload["player_id"] = player_id
    if team_name:
        payload["team_name"] = team_name
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """トークンを検証してペイロードを返す。無効な場合は None。"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.debug("JWT verification failed: %s", e)
        return None
