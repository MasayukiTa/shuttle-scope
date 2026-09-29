"""Ray リモートタスク定義 (INFRA Phase D)

- Ray 利用可能時のみ @ray.remote をかぶせる
- 未インストール時は素の関数として扱う
- タスク本体は backend/cv / backend/pipeline を呼ぶだけ
  (Phase B 未実装でも import エラーにならないように内部で遅延 import)
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def _maybe_remote(num_cpus: Optional[float] = None, num_gpus: Optional[float] = None) -> Callable:
    """ray が利用可能なら @ray.remote、そうでなければ恒等デコレータを返すヘルパ"""

    def decorator(fn: Callable) -> Callable:
        try:
            import ray  # type: ignore
        except Exception:
            # ray が無い環境では素の関数として残す
            return fn

        try:
            options = {}
            if num_cpus is not None:
                options["num_cpus"] = num_cpus
            if num_gpus is not None:
                options["num_gpus"] = num_gpus
            if options:
                return ray.remote(**options)(fn)
            return ray.remote(fn)
        except Exception as exc:  # pragma: no cover
            logger.warning("_maybe_remote: ray.remote 付与失敗 (%s)。素の関数を使用。", exc)
            return fn

    return decorator


# ─────────────────────────────────────────────────────────────
# タスク本体: すべて「薄いラッパ」
# backend/cv/ backend/pipeline/ 側の実装は Phase B で拡張される想定。
# この層では import エラーを握りつぶし、未実装なら {"status": "skipped"} を返す。
# ─────────────────────────────────────────────────────────────


def _safe_call(import_path: str, func_name: str, *args: Any, **kwargs: Any) -> Any:
    """遅延 import して関数を実行。import 失敗時は skipped を返す。"""
    try:
        module = __import__(import_path, fromlist=[func_name])
        fn = getattr(module, func_name, None)
        if fn is None:
            logger.info("_safe_call: %s.%s 未実装", import_path, func_name)
            return {"status": "skipped", "reason": f"{import_path}.{func_name} not found"}
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("_safe_call: %s.%s 実行失敗 (%s)", import_path, func_name, exc)
        return {"status": "error", "error": str(exc)}


# 動画ファイルはPC1にしかないため ray.remote は付けない
# 分散推論は pipeline._run_tracknet_distributed() が担当する
def run_tracknet(video_path: str, **kwargs: Any) -> Any:
    """TrackNet によるシャトル軌跡推定（PC1ローカル実行）"""
    return _safe_call("backend.cv.tracknet_runner", "run_tracknet", video_path, **kwargs)


# Poseも動画ファイルへのアクセスが必要なためPC1ローカル実行
def run_mediapipe(video_path: str, **kwargs: Any) -> Any:
    """MediaPipe による姿勢推定（PC1ローカル実行）"""
    return _safe_call("backend.cv.mediapipe_runner", "run_mediapipe", video_path, **kwargs)


@_maybe_remote(num_cpus=1)
def extract_clips(video_path: str, rally_bounds: Any = None, **kwargs: Any) -> Any:
    """ラリー単位クリップ抽出"""
    return _safe_call("backend.pipeline.clips", "extract_clips", video_path, rally_bounds, **kwargs)


@_maybe_remote(num_cpus=1)
def run_statistics(video_id: int, **kwargs: Any) -> Any:
    """統計量算出"""
    return _safe_call("backend.pipeline.statistics", "run_statistics", video_id, **kwargs)


@_maybe_remote(num_cpus=1)
def calc_center_of_gravity(video_id: int, **kwargs: Any) -> Any:
    """重心位置算出"""
    return _safe_call("backend.pipeline.cog", "calc_center_of_gravity", video_id, **kwargs)


@_maybe_remote(num_cpus=1)
def classify_shots(video_id: int, **kwargs: Any) -> Any:
    """ショット分類"""
    return _safe_call("backend.pipeline.shot_classifier", "classify_shots", video_id, **kwargs)
