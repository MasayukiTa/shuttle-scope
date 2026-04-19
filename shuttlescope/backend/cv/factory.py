"""CV Inferencer 実装切替の唯一の入口。

選択優先順位:
    SS_CV_MOCK=1      → 常に Mock を返す (テスト / 非 CUDA 開発機)
    SS_USE_GPU=1      → CUDA を試行 → 失敗時 OpenVINO → 失敗時 CPU → 最終 Mock
    SS_USE_GPU=0      → OpenVINO を試行 → 失敗時 CPU → 最終 Mock

OpenVINO は CUDA 不在の K10 ワーカーでも動作する（CPU モードにフォールバック）。
routers / pipeline は必ず get_tracknet() / get_pose() のみを使うこと。

キャッシュ方針:
    環境変数 (SS_CV_MOCK / SS_USE_GPU / SS_CUDA_DEVICE) の組み合わせをキーにして
    解決済みインスタンスをキャッシュする。同一環境での二重初期化と重複警告を防ぐ。
    環境変数が変化した場合（ベンチマークの _env_override 等）は再解決する。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from backend.cv.base import PoseInferencer, TrackNetInferencer

logger = logging.getLogger(__name__)

# ─── キャッシュ ────────────────────────────────────────────────────────────────

_tracknet_cache: Optional[dict] = None  # {"key": tuple, "impl": TrackNetInferencer}
_pose_cache: Optional[dict] = None      # {"key": tuple, "impl": PoseInferencer}


def _env_key() -> tuple:
    """現在の環境変数からキャッシュキーを生成する。"""
    return (
        os.environ.get("SS_CV_MOCK", "0"),
        os.environ.get("SS_USE_GPU", "0"),
        os.environ.get("SS_CUDA_DEVICE", "0"),
    )


def clear_cache() -> None:
    """キャッシュを破棄する（テスト用・環境変更後の強制再解決用）。"""
    global _tracknet_cache, _pose_cache
    _tracknet_cache = None
    _pose_cache = None


def _settings():
    # 遅延 import で循環依存を避ける
    from backend.config import settings

    return settings


def get_tracknet() -> TrackNetInferencer:
    """TrackNet 実装を返す。失敗時は順次フォールバック。

    優先順: Mock > CUDA(torch) > OpenVINO > CPU(classical CV) > Mock
    同一環境下での二重呼び出しはキャッシュを返すため警告は初回のみ出力される。
    """
    global _tracknet_cache

    key = _env_key()
    if _tracknet_cache is not None and _tracknet_cache["key"] == key:
        return _tracknet_cache["impl"]

    impl = _resolve_tracknet(key)
    _tracknet_cache = {"key": key, "impl": impl}
    return impl


def _resolve_tracknet(key: tuple) -> TrackNetInferencer:
    s = _settings()

    # 最優先: Mock
    if int(s.ss_cv_mock) == 1:
        from backend.cv.tracknet_mock import MockTrackNet

        logger.info("[cv.factory] TrackNet: Mock を使用 (SS_CV_MOCK=1)")
        return MockTrackNet()

    # CUDA 経路（SS_USE_GPU=1 かつ torch + CUDA 利用可能時）
    if int(s.ss_use_gpu) == 1:
        try:
            from backend.cv.tracknet_cuda import CudaTrackNet

            impl = CudaTrackNet(device_index=int(s.ss_cuda_device))
            logger.info("[cv.factory] TrackNet: CUDA 実装を使用")
            return impl
        except (ImportError, RuntimeError) as exc:
            logger.warning(
                "[cv.factory] CUDA TrackNet 使用不可: %s — OpenVINO にフォールバック", exc
            )

    # ONNX/OpenVINO 経路（SS_USE_GPU=1 なら CUDA EP、SS_USE_GPU=0 なら ONNX CPU を選択）
    # OpenVINOTrackNet は内部で TrackNetInference.load() を呼び、
    # SS_USE_GPU の値に応じて CUDA EP / OpenVINO / ONNX CPU を自動選択する。
    try:
        from backend.cv.tracknet_openvino import OpenVINOTrackNet

        impl = OpenVINOTrackNet()
        logger.info("[cv.factory] TrackNet: OpenVINOTrackNet (backend=%s) を使用",
                    impl._impl.backend_name() if hasattr(impl, '_impl') else '?')
        return impl
    except (ImportError, RuntimeError) as exc:
        logger.warning(
            "[cv.factory] OpenVINO TrackNet 使用不可: %s — CPU にフォールバック", exc
        )

    # CPU 経路（classical CV、どの環境でも動作）
    try:
        from backend.cv.tracknet_cpu import CpuTrackNet

        impl = CpuTrackNet()
        logger.info("[cv.factory] TrackNet: CPU 実装を使用")
        return impl
    except (ImportError, RuntimeError) as exc:
        logger.warning("[cv.factory] CPU TrackNet 使用不可: %s — Mock にフォールバック", exc)

    # 最終フォールバック: Mock
    from backend.cv.tracknet_mock import MockTrackNet

    logger.info("[cv.factory] TrackNet: Mock にフォールバック")
    return MockTrackNet()


def get_pose() -> PoseInferencer:
    """Pose 実装を返す。失敗時は順次フォールバック。

    優先順: Mock > CUDA(MediaPipe GPU) > CPU(MediaPipe CPU) > Mock
    同一環境下での二重呼び出しはキャッシュを返すため警告は初回のみ出力される。
    """
    global _pose_cache

    key = _env_key()
    if _pose_cache is not None and _pose_cache["key"] == key:
        return _pose_cache["impl"]

    impl = _resolve_pose(key)
    _pose_cache = {"key": key, "impl": impl}
    return impl


def _resolve_pose(key: tuple) -> PoseInferencer:
    s = _settings()

    if int(s.ss_cv_mock) == 1:
        from backend.cv.pose_mock import MockPose

        logger.info("[cv.factory] Pose: Mock を使用 (SS_CV_MOCK=1)")
        return MockPose()

    if int(s.ss_use_gpu) == 1:
        try:
            from backend.cv.pose_cuda import CudaPose

            impl = CudaPose()
            logger.info("[cv.factory] Pose: CUDA 実装を使用")
            return impl
        except (ImportError, RuntimeError) as exc:
            logger.warning("[cv.factory] CUDA Pose 使用不可: %s — CPU にフォールバック", exc)

    try:
        from backend.cv.pose_cpu import CpuPose

        impl = CpuPose()
        logger.info("[cv.factory] Pose: CPU 実装を使用")
        return impl
    except (ImportError, RuntimeError) as exc:
        logger.warning("[cv.factory] CPU Pose 使用不可: %s — Mock にフォールバック", exc)

    from backend.cv.pose_mock import MockPose

    logger.info("[cv.factory] Pose: Mock にフォールバック")
    return MockPose()
