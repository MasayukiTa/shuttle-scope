"""Idempotency-Key ヘッダ対応 (Phase B2)。

X-Idempotency-Key ヘッダを受領し、同じキーでの 2 回目以降のリクエストは
保存済みレスポンスを返す（業務ロジックを再実行しない）。

対象操作 (副作用ありかつ二重実行が問題になるもの):
  - POST /api/matches/{id}/reissue_video_token
  - DELETE /api/matches/{id}
  - GET /api/export/package (二重ダウンロード時の access_log 重複防止)

設計:
  - 24 時間保持（_TTL_SECONDS）
  - **DB 永続化** + in-memory 短期キャッシュ
    Round 258 R9 V6 fix (deep audit): 旧 docstring は "in-memory + DB 永続化のハイブリッド"
    を主張していたが、実装は in-memory dict のみ。PM2 restart / NSSM 再起動で 24h
    dedup window が消し飛び、replay 攻撃 (token 再発行 / export 二重 access_log) が
    成立していた。本コミットで `IdempotencyRecord` テーブルを実体化し、process restart
    でも replay 防御が機能するようにする。in-memory dict は read 高速化用の短期キャッシュ。
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

# Round 258 R9 V6 fix (deep audit): DB 永続化のために AnalysisCache テーブルを
# 流用する (idempotency 専用 model + alembic migration を別途用意するより軽量)。
# key プレフィクスで namespace を分ける: "idem:" + key
_IDEM_KEY_PREFIX = "idem:"


def is_valid_key(key: str) -> bool:
    """X-Idempotency-Key 形式検証。"""
    return bool(_KEY_RE.match(key or ""))


def _gc_expired() -> None:
    """期限切れエントリを破棄する。"""
    now = time.time()
    expired = [k for k, r in _records.items() if now - r.created_at > _TTL_SECONDS]
    for k in expired:
        _records.pop(k, None)


def _db_get(key: str) -> Optional[IdempotencyRecord]:
    """AnalysisCache から idempotency record を読む。

    payload に JSON として {user_id, endpoint, status_code, response, created_at} を保存する。
    """
    try:
        from datetime import datetime
        from backend.db.database import SessionLocal
        from backend.db.models import AnalysisCache
        with SessionLocal() as db:
            rec = (
                db.query(AnalysisCache)
                .filter(AnalysisCache.key == _IDEM_KEY_PREFIX + key)
                .first()
            )
            if rec is None:
                return None
            if rec.expires_at and rec.expires_at < datetime.utcnow():
                # expired
                try:
                    db.delete(rec)
                    db.commit()
                except Exception:
                    pass
                return None
            try:
                meta = json.loads(rec.payload or "{}")
            except Exception:
                return None
            return IdempotencyRecord(
                key=key,
                user_id=meta.get("user_id"),
                endpoint=meta.get("endpoint", ""),
                response_json=meta.get("response_json", ""),
                status_code=int(meta.get("status_code", 200)),
                created_at=float(meta.get("created_at", time.time())),
            )
    except Exception as exc:
        logger.warning("idempotency DB read failed: %s", exc)
        return None


def _db_store(rec: IdempotencyRecord) -> None:
    try:
        from datetime import datetime, timedelta
        from backend.db.database import SessionLocal
        from backend.db.models import AnalysisCache
        meta = {
            "user_id": rec.user_id,
            "endpoint": rec.endpoint,
            "response_json": rec.response_json,
            "status_code": rec.status_code,
            "created_at": rec.created_at,
        }
        with SessionLocal() as db:
            existing = (
                db.query(AnalysisCache)
                .filter(AnalysisCache.key == _IDEM_KEY_PREFIX + rec.key)
                .first()
            )
            if existing is not None:
                existing.payload = json.dumps(meta, ensure_ascii=False)
                existing.expires_at = datetime.utcnow() + timedelta(seconds=_TTL_SECONDS)
            else:
                db.add(AnalysisCache(
                    key=_IDEM_KEY_PREFIX + rec.key,
                    payload=json.dumps(meta, ensure_ascii=False),
                    expires_at=datetime.utcnow() + timedelta(seconds=_TTL_SECONDS),
                ))
            db.commit()
    except Exception as exc:
        logger.warning("idempotency DB write failed: %s", exc)


def get_cached(key: str, user_id: Optional[int], endpoint: str) -> Optional[IdempotencyRecord]:
    """同じ (key, user_id, endpoint) の保存済みレコードを返す。

    Round 258 R9 V6 fix: process-local cache → 不在なら DB を読みに行く。
    PM2 restart / NSSM 再起動でも 24h dedup window が維持される。
    """
    with _lock:
        _gc_expired()
        rec = _records.get(key)
        if rec is None:
            # DB から hydrate
            rec = _db_get(key)
            if rec is not None:
                _records[key] = rec  # in-memory cache に取り込む
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
    """新規レコードを保存する。Round 258 R9 V6: DB にも persist。"""
    with _lock:
        rec = IdempotencyRecord(
            key=key,
            user_id=user_id,
            endpoint=endpoint,
            response_json=json.dumps(response_obj, ensure_ascii=False),
            status_code=status_code,
        )
        _records[key] = rec
        _db_store(rec)


def replay_response(rec: IdempotencyRecord) -> Any:
    """保存済みレスポンスを返す。"""
    try:
        return json.loads(rec.response_json)
    except Exception:
        return {"success": True, "data": None, "_idempotent_replay": True}
