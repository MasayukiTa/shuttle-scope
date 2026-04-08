"""
sync_meta.py — 同期メタデータ更新ヘルパー

CRUD エンドポイントで create / update / delete 時に呼び出し、
updated_at と revision を確実に更新する。
"""
from __future__ import annotations

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
