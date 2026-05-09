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

    Round 258 R10 P0 fix (regression audit): R9 で AnalysisCache.key / .payload と
    書いていたが実際の column 名は cache_key / result_json で、毎回 AttributeError
    で warning に落ちて in-memory-only に degrade していた (V6 fix が完全 noop)。
    正しい column 名 + NOT NULL 制約 (player_id / analysis_type / filters_json /
    expires_at) を満たす形で書き直す。
    """
    try:
        from datetime import datetime
        from backend.db.database import SessionLocal
        from backend.db.models import AnalysisCache
        with SessionLocal() as db:
            rec = (
                db.query(AnalysisCache)
                .filter(AnalysisCache.cache_key == _IDEM_KEY_PREFIX + key)
                .first()
            )
            if rec is None:
                return None
            if rec.expires_at and rec.expires_at < datetime.utcnow():
                try:
                    db.delete(rec)
                    db.commit()
                except Exception:
                    pass
                return None
            try:
                meta = json.loads(rec.result_json or "{}")
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
        meta_json = json.dumps(meta, ensure_ascii=False)
        # Round 258 R10 P0 fix: cache_key / result_json + NOT NULL 列 (player_id /
        # analysis_type / filters_json) もすべて埋める。idempotency は player に
        # 紐付かないので player_id=0 (sentinel) を入れて区別。
        now = datetime.utcnow()
        expires = now + timedelta(seconds=_TTL_SECONDS)
        with SessionLocal() as db:
            existing = (
                db.query(AnalysisCache)
                .filter(AnalysisCache.cache_key == _IDEM_KEY_PREFIX + rec.key)
                .first()
            )
            if existing is not None:
                # Round 258 R18 P1 fix (R18a-2 P1-2): 旧コードは `existing` を盲目的に
                # 上書きしていたが、`get_cached` は `(key, user_id, endpoint)` ミスマッチ
                # 時に **None を返して通常実行を進める** ため、別ユーザの key と衝突
                # した場合に store() が ORIGINAL ユーザのレコードを silently 破壊する
                # 経路があった。結果、元ユーザの再 POST は replay されず再実行され、
                # 二重課金 / 二重副作用が起こり得た。
                # 修正: existing を読み直し、(user_id, endpoint) ペアが一致しない場合
                # は **書き込みを抑止して warn ログのみ**。元レコードの replay 情報を
                # 守り、衝突した別ユーザは "ただし replay 不能" な代償として
                # 通常実行 (副作用) のみが進む状態にする。
                try:
                    existing_meta = json.loads(existing.result_json or "{}")
                    if (
                        existing_meta.get("user_id") != rec.user_id
                        or existing_meta.get("endpoint") != rec.endpoint
                    ):
                        logger.warning(
                            "idempotency key collision across users/endpoints: "
                            "key=%s existing_user=%s requesting_user=%s — refusing overwrite",
                            rec.key, existing_meta.get("user_id"), rec.user_id,
                        )
                        # commit せず return (other branch の db.commit にも到達しない)
                        return
                except Exception:
                    # parse 失敗時は安全側 (上書きしない) に倒す
                    logger.warning("idempotency existing meta unparsable for key=%s; refusing overwrite", rec.key)
                    return
                existing.result_json = meta_json
                existing.expires_at = expires
                existing.computed_at = now
            else:
                db.add(AnalysisCache(
                    cache_key=_IDEM_KEY_PREFIX + rec.key,
                    player_id=0,  # idempotency 用 sentinel
                    analysis_type="idempotency",
                    filters_json="{}",
                    result_json=meta_json,
                    sample_size=0,
                    confidence_level=0.0,
                    computed_at=now,
                    expires_at=expires,
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
