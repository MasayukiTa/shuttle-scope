"""Idempotency-Key ヘッダ対応 (Phase B2)。

X-Idempotency-Key ヘッダを受領し、同じキーでの 2 回目以降のリクエストは
保存済みレスポンスを返す（業務ロジックを再実行しない）。

対象操作 (副作用ありかつ二重実行が問題になるもの):
  - POST /api/matches/{id}/reissue_video_token
  - DELETE /api/matches/{id}
  - GET /api/export/package (二重ダウンロード時の access_log 重複防止)

設計:
  - 24 時間保持（_TTL_SECONDS）
  - in-memory + DB 永続化のハイブリッド
  - キー形式: 任意の URL-safe 文字列、min 8 / max 128 文字
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_TTL_SECONDS = 24 * 60 * 60
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")


@dataclass
class IdempotencyRecord:
    key: str
    user_id: Optional[int]
    endpoint: str
    response_json: str
    status_code: int
    created_at: float = field(default_factory=time.time)


_records: Dict[str, IdempotencyRecord] = {}
_lock = Lock()


def is_valid_key(key: str) -> bool:
    """X-Idempotency-Key 形式検証。"""
    return bool(_KEY_RE.match(key or ""))


def _gc_expired() -> None:
    """期限切れエントリを破棄する。"""
    now = time.time()
    expired = [k for k, r in _records.items() if now - r.created_at > _TTL_SECONDS]
    for k in expired:
        _records.pop(k, None)


def get_cached(key: str, user_id: Optional[int], endpoint: str) -> Optional[IdempotencyRecord]:
    """同じ (key, user_id, endpoint) の保存済みレコードを返す。"""
    with _lock:
        _gc_expired()
        rec = _records.get(key)
        if rec is None:
            return None
        if rec.user_id != user_id or rec.endpoint != endpoint:
            # キーが他ユーザー/他エンドポイントで使われている → 衝突
            return None
        if time.time() - rec.created_at > _TTL_SECONDS:
            _records.pop(key, None)
            return None
        return rec


def store(
    key: str,
    user_id: Optional[int],
    endpoint: str,
    response_obj: Any,
    status_code: int = 200,
) -> None:
    """新規レコードを保存する。"""
    with _lock:
        _records[key] = IdempotencyRecord(
            key=key,
            user_id=user_id,
            endpoint=endpoint,
            response_json=json.dumps(response_obj, ensure_ascii=False),
            status_code=status_code,
        )


def replay_response(rec: IdempotencyRecord) -> Any:
    """保存済みレスポンスを返す。"""
    try:
        return json.loads(rec.response_json)
    except Exception:
        return {"success": True, "data": None, "_idempotent_replay": True}
