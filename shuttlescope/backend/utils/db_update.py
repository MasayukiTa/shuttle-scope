"""DB モデル更新の共通ヘルパー。

PUT 系ルーターで pydantic payload を ORM オブジェクトに反映する際、
NOT NULL カラムに None が渡されると SQL IntegrityError (HTTP 500) になる。
この 500 を 422 に変換して、攻撃者がエラーレスポンスから内部スキーマを
推測できないようにする。
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.inspection import inspect as _sa_inspect


_NOT_NULL_CACHE: dict[type, frozenset[str]] = {}


def not_null_columns(model_cls) -> frozenset[str]:
    """SQLAlchemy モデルの NOT NULL カラム名セットを返す（キャッシュ付き）。

    主キーと NOT NULL 以外のカラムは除外する。
    """
    cached = _NOT_NULL_CACHE.get(model_cls)
    if cached is not None:
        return cached
    cols = frozenset(
        col.name for col in _sa_inspect(model_cls).columns
        if not col.nullable and not col.primary_key
    )
    _NOT_NULL_CACHE[model_cls] = cols
    return cols


def apply_update(obj: Any, payload: dict[str, Any], *, model_cls: type | None = None) -> None:
    """payload の各キーを obj に setattr する。NOT NULL カラムに None が入っていれば 422。

    Args:
        obj: SQLAlchemy インスタンス (更新対象)
        payload: 更新対象フィールドの dict (通常 body.model_dump(exclude_unset=True))
        model_cls: obj のクラス。省略時は type(obj) を使用
    """
    cls = model_cls or type(obj)
    nn = not_null_columns(cls)
    for key, value in payload.items():
        if value is None and key in nn:
            raise HTTPException(
                status_code=422,
                detail=f"{key} は null にできません（NOT NULL 制約）",
            )
        setattr(obj, key, value)
