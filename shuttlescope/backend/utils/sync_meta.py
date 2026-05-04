"""
sync_meta.py — 同期メタデータ更新ヘルパー

CRUD エンドポイントで create / update / delete 時に呼び出し、
updated_at / revision / source_device_id / content_hash を確実に更新する。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


def touch(obj: Any) -> None:
    """
    モデルインスタンスの updated_at を現在時刻に、revision を +1 する。
    sync メタデータを持たないモデルに対しても安全（hasattr チェック）。
    """
    now = datetime.utcnow()
    if hasattr(obj, "updated_at"):
        obj.updated_at = now
    if hasattr(obj, "revision") and obj.revision is not None:
        obj.revision = obj.revision + 1
    elif hasattr(obj, "revision"):
        obj.revision = 1


def compute_content_hash(payload: dict) -> str:
    """ペイロード dict の正規化 JSON を SHA-256 ハッシュして返す。"""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def get_device_id(db: Any) -> str:
    """設定テーブルから sync_device_id を取得する。取得できない場合は空文字を返す。"""
    from sqlalchemy import text
    try:
        row = db.execute(text("SELECT value FROM app_settings WHERE key = 'sync_device_id'")).fetchone()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return ""


def touch_sync_metadata(
    obj: Any,
    payload_like: dict | None = None,
    device_id: str = "",
) -> None:
    """
    updated_at / revision / source_device_id / content_hash を一括更新する。

    Args:
        obj:          SQLAlchemy モデルインスタンス
        payload_like: content_hash 計算用のペイロード dict（None の場合はハッシュ更新スキップ）
        device_id:    source_device_id に設定するデバイス識別子（空文字の場合はスキップ）
    """
    touch(obj)
    if device_id and hasattr(obj, "source_device_id"):
        obj.source_device_id = device_id
    if payload_like is not None and hasattr(obj, "content_hash"):
        obj.content_hash = compute_content_hash(payload_like)
