"""CV Inferencer 実装切替の唯一の入口。

選択優先順位:
    SS_CV_MOCK=1      → 常に Mock を返す (テスト / 非 CUDA 開発機)
    SS_USE_GPU=1      → CUDA を試行 → 失敗時 OpenVINO → 失敗時 CPU → 最終 Mock
    SS_USE_GPU=0      → OpenVINO を試行 → 失敗時 CPU → 最終 Mock

OpenVINO は CUDA 不在の K10 ワーカーでも動作する（CPU モードにフォールバック）。
routers / pipeline は必ず get_tracknet() / get_pose() のみを使うこと。
"""
from __future__ import annotations

import logging

from backend.cv.base import PoseInferencer, TrackNetInferencer

logger = logging.getLogger(__name__)


def _settings():
    # 遅延 import で循環依存を避ける
    from backend.config import settings

    return settings


def get_tracknet() -> TrackNetInferencer:
    """TrackNet 実装を返す。失敗時は順次フォールバック。

    優先順: Mock > CUDA(torch) > OpenVINO > CPU(classical CV) > Mock
    """
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

    # OpenVINO 経路（CUDA 不在でも動作。K10 CPU でもフォールバックあり）
    try:
        from backend.cv.tracknet_openvino import OpenVINOTrackNet

        impl = OpenVINOTrackNet()
        logger.info("[cv.factory] TrackNet: OpenVINO 実装を使用")
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
    """
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
