"""CPU Pose inference powered by MediaPipe Tasks.

This implementation intentionally avoids the legacy ``mp.solutions`` API because
recent MediaPipe releases no longer expose it consistently in CI environments.
"""
from __future__ import annotations

import logging
from typing import List

from backend.cv.base import PoseInferencer, PoseSample
from backend.cv.pose_landmarker_model import resolve_pose_landmarker_model

logger = logging.getLogger(__name__)


class CpuPose(PoseInferencer):
    """MediaPipe Pose implementation using the CPU delegate."""

    @staticmethod
    def _zero_landmarks() -> List[dict]:
        return [
            {"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}
            for _ in range(33)
        ]

    def __init__(self) -> None:
        try:
            import mediapipe as mp  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "mediapipe is required to initialize CpuPose."
            ) from exc

        try:
            import cv2  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "opencv-python (cv2) is required to initialize CpuPose."
            ) from exc

        try:
            from mediapipe.tasks import python as mp_tasks  # noqa: F401
            from mediapipe.tasks.python import vision as mp_vision  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "mediapipe.tasks is required to initialize CpuPose."
            ) from exc

        self._model_path = resolve_pose_landmarker_model(download_if_missing=True)

    def run(self, video_path: str) -> List[PoseSample]:
        """Read a video and return one 33-landmark sample per frame."""
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python as mp_tasks
        from mediapipe.tasks.python import vision as mp_vision

        samples: List[PoseSample] = []

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        base_options = mp_tasks.BaseOptions(
            model_asset_path=str(self._model_path),
            delegate=mp_tasks.BaseOptions.Delegate.CPU,
        )
        options = mp_vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_poses=1,
        )

        try:
            try:
                pose = mp_vision.PoseLandmarker.create_from_options(options)
            except (OSError, RuntimeError) as exc:
                logger.warning(
                    "[cv.pose_cpu] PoseLandmarker unavailable, falling back to zero landmarks: %s",
                    exc,
                )
                pose = None

            frame_idx = 0
            while True:
                ok, frame_bgr = cap.read()
                if not ok:
                    break

                ts_sec = frame_idx / float(fps) if fps > 0 else 0.0
                landmarks_list = self._zero_landmarks()

                if pose is not None:
                    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(
                        image_format=mp.ImageFormat.SRGB,
                        data=frame_rgb,
                    )
                    ts_ms = int((frame_idx / float(fps)) * 1000.0) if fps > 0 else frame_idx
                    result = pose.detect_for_video(mp_image, ts_ms)

                    detected_landmarks = []
                    if (
                        result is not None
                        and getattr(result, "pose_landmarks", None)
                        and len(result.pose_landmarks) > 0
                    ):
                        for lm in result.pose_landmarks[0]:
                            detected_landmarks.append(
                                {
                                    "x": float(lm.x),
                                    "y": float(lm.y),
                                    "z": float(lm.z),
                                    "visibility": float(getattr(lm, "visibility", 0.0)),
                                }
                            )
                    if len(detected_landmarks) == 33:
                        landmarks_list = detected_landmarks

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
            if "pose" in locals() and pose is not None:
                pose.close()
            cap.release()

        return samples
