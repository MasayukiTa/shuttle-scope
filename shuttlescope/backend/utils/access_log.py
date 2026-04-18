"""アクセスログ書き込みヘルパー（A-2）"""
import json
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def log_access(
    db,
    action: str,
    user_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    details: Optional[dict] = None,
    ip_addr: Optional[str] = None,
) -> None:
    """AccessLog に 1 件書き込む。失敗しても例外を上位に伝播しない。"""
    try:
        from backend.db.models import AccessLog
        entry = AccessLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details, ensure_ascii=False) if details else None,
            ip_addr=ip_addr,
            created_at=datetime.utcnow(),
        )
        db.add(entry)
        db.commit()
    except Exception as exc:
        logger.warning("access_log write failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
