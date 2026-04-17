"""GPU Pose inference powered by MediaPipe Tasks."""
from __future__ import annotations

import logging
from typing import List, Optional

from backend.cv.base import PoseInferencer, PoseSample
from backend.cv.pose_landmarker_model import resolve_pose_landmarker_model

logger = logging.getLogger(__name__)


class CudaPose(PoseInferencer):
    """MediaPipe Tasks implementation using the GPU delegate when available."""

    def __init__(self, device_index: int = 0) -> None:
        self._device_index = device_index

        try:
            import mediapipe as mp  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "mediapipe is required to initialize CudaPose."
            ) from exc

        try:
            from mediapipe.tasks import python as mp_tasks  # noqa: F401
            from mediapipe.tasks.python import vision as mp_vision  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "mediapipe.tasks is required to initialize CudaPose."
            ) from exc

        self._model_path = resolve_pose_landmarker_model(download_if_missing=True)
        self._cpu_fallback: Optional[PoseInferencer] = None

    def _make_landmarker(self):
        from mediapipe.tasks import python as mp_tasks
        from mediapipe.tasks.python import vision as mp_vision

        base_options = mp_tasks.BaseOptions(
            model_asset_path=str(self._model_path),
            delegate=mp_tasks.BaseOptions.Delegate.GPU,
        )
        options = mp_vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_poses=1,
        )
        return mp_vision.PoseLandmarker.create_from_options(options)

    def _fallback_to_cpu(self, video_path: str, reason: str) -> List[PoseSample]:
        logger.warning(
            "[cv.pose_cuda] GPU pose failed: %s; falling back to CpuPose",
            reason,
        )
        if self._cpu_fallback is None:
            try:
                from backend.cv.pose_cpu import CpuPose

                self._cpu_fallback = CpuPose()
            except ImportError:
                from backend.cv.pose_mock import MockPose

                self._cpu_fallback = MockPose()
        return self._cpu_fallback.run(video_path)

    def run(self, video_path: str) -> List[PoseSample]:
        import cv2
        import mediapipe as mp

        try:
            landmarker = self._make_landmarker()
        except Exception as exc:  # noqa: BLE001
            return self._fallback_to_cpu(video_path, f"landmarker init failed: {exc}")

        samples: List[PoseSample] = []
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            landmarker.close()
            raise RuntimeError(f"Failed to open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        try:
            frame_idx = 0
            while True:
                ok, frame_bgr = cap.read()
                if not ok:
                    break

                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=frame_rgb,
                )
                ts_ms = int((frame_idx / float(fps)) * 1000.0) if fps > 0 else frame_idx
                try:
                    result = landmarker.detect_for_video(mp_image, ts_ms)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[cv.pose_cuda] frame %d GPU inference failed: %s",
                        frame_idx,
                        exc,
                    )
                    result = None

                ts_sec = frame_idx / float(fps) if fps > 0 else 0.0
                landmarks_list = []
                if (
                    result is not None
                    and getattr(result, "pose_landmarks", None)
                    and len(result.pose_landmarks) > 0
                ):
                    for lm in result.pose_landmarks[0]:
                        landmarks_list.append(
                            {
                                "x": float(lm.x),
                                "y": float(lm.y),
                                "z": float(lm.z),
                                "visibility": float(getattr(lm, "visibility", 0.0)),
                            }
                        )
                if len(landmarks_list) != 33:
                    landmarks_list = [
                        {"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}
                        for _ in range(33)
                    ]

                samples.append(
                    PoseSample(
                        frame=frame_idx,
                        ts_sec=ts_sec,
                        side="a",
                        landmarks=landmarks_list,
                    )
                )
                frame_idx += 1
        finally:
            cap.release()
            landmarker.close()

        return samples
