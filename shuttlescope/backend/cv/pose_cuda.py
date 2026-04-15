"""Pose の CUDA 実装 (MediaPipe Tasks API, GPU delegate)。

設計方針:
    - MediaPipe の Solutions API は Python から GPU delegate を直接指定できない。
    - そこで新しい Tasks API (mediapipe.tasks.vision.PoseLandmarker) を利用し、
      BaseOptions(delegate=Delegate.GPU) を指定して GPU 推論を試みる。
    - Tasks API 非対応、もしくはモデルファイル未配置の場合は
      CPU 実装 (CpuPose) にフォールバックし warn ログを出す。

モデルファイル:
    - 既定パス: backend/cv/models/pose_landmarker_lite.task
    - 環境変数 SS_POSE_LANDMARKER_MODEL で上書き可。
    - ダウンロード手順 (同梱しない):
        curl -L -o backend/cv/models/pose_landmarker_lite.task \
          https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

from backend.cv.base import PoseInferencer, PoseSample

logger = logging.getLogger(__name__)

# 既定モデル配置パス (リポジトリには同梱しない)
_DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parent / "models" / "pose_landmarker_lite.task"
)


class CudaPose(PoseInferencer):
    """MediaPipe Tasks API (GPU delegate) による姿勢推論。

    初期化時に Tasks API & モデルファイルの可用性を確認し、
    使えない場合は ImportError を送出 (factory 側で CPU/Mock にフォールバック)。
    """

    def __init__(self, device_index: int = 0) -> None:
        self._device_index = device_index  # 将来の multi-GPU 用に保持のみ

        try:
            import mediapipe as mp  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "mediapipe が未インストールのため CudaPose を初期化できません。"
            ) from exc

        # Tasks API の存在チェック
        try:
            from mediapipe.tasks import python as mp_tasks  # noqa: F401
            from mediapipe.tasks.python import vision as mp_vision  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "mediapipe.tasks API が利用できないため CudaPose を初期化できません。"
            ) from exc

        # モデルファイルの所在確認
        model_path_env = os.environ.get("SS_POSE_LANDMARKER_MODEL")
        self._model_path: Path = (
            Path(model_path_env) if model_path_env else _DEFAULT_MODEL_PATH
        )
        if not self._model_path.exists():
            raise ImportError(
                f"PoseLandmarker モデルファイルが見つかりません: {self._model_path}. "
                "ダウンロード手順は backend/cv/pose_cuda.py の docstring を参照。"
            )

        # 内部キャッシュ: フォールバック先 CpuPose
        self._cpu_fallback: Optional[PoseInferencer] = None

    def _make_landmarker(self):
        """GPU delegate の PoseLandmarker を構築。失敗時は例外を送出。"""
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
        """CPU 版にフォールバック。警告ログを出す。"""
        logger.warning(
            "[cv.pose_cuda] GPU 推論失敗: %s — CpuPose にフォールバック", reason
        )
        if self._cpu_fallback is None:
            # 遅延生成: mediapipe/cv2 未インストールなら更に Mock に落ちる
            try:
                from backend.cv.pose_cpu import CpuPose

                self._cpu_fallback = CpuPose()
            except ImportError:
                from backend.cv.pose_mock import MockPose

                self._cpu_fallback = MockPose()
        return self._cpu_fallback.run(video_path)

    def run(self, video_path: str) -> List[PoseSample]:
        """動画を 1 フレームずつ PoseLandmarker.detect_for_video に渡して推論する。"""
        import cv2
        import mediapipe as mp

        try:
            landmarker = self._make_landmarker()
        except Exception as exc:  # noqa: BLE001 - GPU 初期化失敗は多岐
            return self._fallback_to_cpu(video_path, f"landmarker 作成失敗: {exc}")

        samples: List[PoseSample] = []
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            landmarker.close()
            raise RuntimeError(f"動画を開けませんでした: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        try:
            frame_idx = 0
            while True:
                ok, frame_bgr = cap.read()
                if not ok:
                    break

                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                # mediapipe.Image でラップ
                mp_image = mp.Image(
                    image_format=mp.ImageFormat.SRGB, data=frame_rgb
                )
                ts_ms = int((frame_idx / float(fps)) * 1000.0) if fps > 0 else frame_idx
                try:
                    result = landmarker.detect_for_video(mp_image, ts_ms)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[cv.pose_cuda] フレーム %d の GPU 推論例外: %s",
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
                    # Tasks API は list[list[NormalizedLandmark]] を返す (num_poses 次元)
                    for lm in result.pose_landmarks[0]:
                        landmarks_list.append(
                            {
                                "x": float(lm.x),
                                "y": float(lm.y),
                                "z": float(lm.z),
                                "visibility": float(getattr(lm, "visibility", 0.0)),
                            }
                        )
                # 検出失敗 or 不足時は 33 点ぶんゼロ埋め (contract 維持)
                if len(landmarks_list) != 33:
                    landmarks_list = [
                        {"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}
                        for _ in range(33)
                    ]

                # Phase A: side は 'a' 固定。将来 2 選手分 ('a'/'b') に拡張予定。
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
