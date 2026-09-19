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


#: content_hash の対象から外す列。
#:
#: - 同期メタそのもの（updated_at / revision / …）は、内容が同じでも端末ごとに違う
#: - `id` は端末ごとのオートインクリメント。行の identity は `uuid` のほう
#: - `created_at` は同じ行でも取り込み側で変わりうる
_SYNC_META_COLUMNS = frozenset({
    "id", "uuid", "created_at", "updated_at", "revision",
    "source_device_id", "content_hash", "deleted_at",
})


def business_payload(obj: Any) -> dict:
    """**保存後の行**の業務列だけを取り出す。

    リクエストボディではなく行を見ること。部分更新（PATCH のように一部の
    列だけ送る形）では、送った内容をハッシュすると「同じ行を同じ値にした
    2 端末」のハッシュが食い違い、競合でないものが競合になる。

    外部キー (`*_id`) も外している。これらは端末ごとのオートインクリメントで、
    同じ行でも値が違う。含めると**あらゆる行が常に不一致**になり、
    近接タイムスタンプの更新がすべて競合に化ける。
    **代償**: 「親だけ付け替えた」変更はハッシュに出ない。検出漏れであって
    誤検出ではないので、いまの「一度も発火しない」状態よりは厳密に良い。
    親の付け替えまで見るなら、FK を関連行の uuid に解決してから入れること
    （DB アクセスが要るのでこの関数には置いていない）。
    """
    out: dict = {}
    for col in obj.__table__.columns:
        name = col.name
        if name in _SYNC_META_COLUMNS or name.endswith("_id"):
            continue
        val = getattr(obj, name, None)
        if isinstance(val, datetime):
            val = val.isoformat()
        out[name] = val
    return out


def touch(obj: Any) -> None:
    """
    モデルインスタンスの updated_at を現在時刻に、revision を +1 する。
    sync メタデータを持たないモデルに対しても安全（hasattr チェック）。

    **content_hash もここで入れる。** 中核 5 テーブル
    (matches / players / rallies / sets / strokes) のルータは `touch()` は
    呼ぶが `touch_sync_metadata()` は 1 箇所も呼んでおらず、`content_hash` が
    NULL のままだった。`merge_resolver` の競合枝は
    `inc_hash and loc_hash` の両方を要求するので、**競合は構造上一度も
    発火しない**（無言の last-writer-wins）。`revision` は誰も読まないため、
    「ベクタークロックがある」という誤った安心だけが残っていた。

    呼ぶのは**業務列を設定し終えたあと**。先に呼ぶと古い値をハッシュする。
    """
    now = datetime.utcnow()
    if hasattr(obj, "updated_at"):
        obj.updated_at = now
    if hasattr(obj, "revision") and obj.revision is not None:
        obj.revision = obj.revision + 1
    elif hasattr(obj, "revision"):
        obj.revision = 1
    if hasattr(obj, "content_hash"):
        obj.content_hash = compute_content_hash(business_payload(obj))


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
