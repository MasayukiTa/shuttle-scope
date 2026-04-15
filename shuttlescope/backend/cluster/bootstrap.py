"""Ray クラスタの起動/停止ラッパ (INFRA Phase D)

設計方針:
- Ray 未インストール環境でも backend 起動・pytest が通ること
- ray の import は関数スコープに閉じる
- SS_CLUSTER_MODE=off のとき一切 Ray を触らない
- 失敗は WARN ログのみ、例外は投げない
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

# Ray 初期化済みフラグ (多重 init 防止)
_ray_initialized: bool = False


def is_ray_available() -> bool:
    """ray パッケージが import 可能かを安全に判定する"""
    try:
        import ray  # noqa: F401
        return True
    except Exception:  # pragma: no cover - 環境依存
        return False


def init_ray(address: Optional[str] = None) -> bool:
    """Ray クラスタに接続する。

    SS_CLUSTER_MODE != "ray" のときは no-op。
    ray 未インストール / 接続失敗時は WARN ログのみで False を返す。
    成功時は True を返す。
    """
    global _ray_initialized

    # クラスタモードが off の場合は一切何もしない
    mode = getattr(settings, "ss_cluster_mode", "off")
    if mode != "ray":
        logger.debug("init_ray: SS_CLUSTER_MODE=%s のためスキップ", mode)
        return False

    if _ray_initialized:
        logger.debug("init_ray: 既に初期化済み")
        return True

    # ray を関数スコープで try-import
    try:
        import ray  # type: ignore
    except Exception as exc:  # ImportError 以外もキャッチ
        logger.warning("init_ray: ray を import できません (%s)。同期フォールバックに切替。", exc)
        return False

    target_address = address or getattr(settings, "ss_ray_address", "auto")

    try:
        if not ray.is_initialized():
            ray.init(address=target_address, ignore_reinit_error=True)
        _ray_initialized = True
        logger.info("init_ray: Ray クラスタ接続成功 address=%s", target_address)
        return True
    except Exception as exc:
        logger.warning("init_ray: Ray 接続に失敗 address=%s err=%s", target_address, exc)
        return False


def shutdown_ray() -> None:
    """Ray クラスタを停止する。未起動なら no-op。"""
    global _ray_initialized

    if not _ray_initialized:
        return

    try:
        import ray  # type: ignore
        if ray.is_initialized():
            ray.shutdown()
        logger.info("shutdown_ray: Ray クラスタを停止しました")
    except Exception as exc:
        logger.warning("shutdown_ray: 停止時に例外 (%s) — 無視", exc)
    finally:
        _ray_initialized = False
