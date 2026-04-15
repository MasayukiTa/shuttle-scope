"""Pose の CPU 実装 (MediaPipe Solutions API, CPU delegate)。

設計方針:
    - mediapipe はトップレベルで import しない。未インストールでも backend 起動は止めない。
    - コンストラクタで import を試み、失敗すれば ImportError を送出する。
      factory.py 側が ImportError を捕捉して Mock にフォールバックする仕組み。
    - 33 ランドマーク × 全フレーム分の PoseSample を返す契約 (backend/cv/base.py)。
"""
from __future__ import annotations

import logging
from typing import List

from backend.cv.base import PoseInferencer, PoseSample

logger = logging.getLogger(__name__)


class CpuPose(PoseInferencer):
    """MediaPipe Pose (CPU) による姿勢推論実装。"""

    def __init__(self) -> None:
        # mediapipe / cv2 をコンストラクタで import し、未インストールなら ImportError。
        # factory 側はこの ImportError を捕捉して Mock に落ちる。
        try:
            import mediapipe as mp  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "mediapipe が未インストールのため CpuPose を初期化できません。"
            ) from exc
        try:
            import cv2  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "opencv-python (cv2) が未インストールのため CpuPose を初期化できません。"
            ) from exc

    def run(self, video_path: str) -> List[PoseSample]:
        """動画を読み込み、1 フレーム毎に MediaPipe Pose を実行して 33 点を返す。

        注意: Phase A では 1 選手分 (side='a') のみ返す。
        2 選手の左右判定 (a/b の振り分け) は将来的に YOLO bbox との突合で実装する。
        """
        import cv2
        import mediapipe as mp

        samples: List[PoseSample] = []

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"動画を開けませんでした: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        # MediaPipe Pose (Solutions API, CPU)
        # static_image_mode=False で動画向けトラッキングを有効化
        # model_complexity=1 は標準精度 / 速度のバランス
        mp_pose = mp.solutions.pose
        try:
            with mp_pose.Pose(
                static_image_mode=False,
                model_complexity=1,
                enable_segmentation=False,
            ) as pose:
                frame_idx = 0
                while True:
                    ok, frame_bgr = cap.read()
                    if not ok:
                        break

                    # BGR → RGB 変換 (MediaPipe は RGB を期待)
                    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                    result = pose.process(frame_rgb)

                    ts_sec = frame_idx / float(fps) if fps > 0 else 0.0
                    landmarks_list = []
                    if result.pose_landmarks is not None:
                        # 33 点ぶんを dict で格納
                        for lm in result.pose_landmarks.landmark:
                            landmarks_list.append(
                                {
                                    "x": float(lm.x),
                                    "y": float(lm.y),
                                    "z": float(lm.z),
                                    "visibility": float(lm.visibility),
                                }
                            )
                    else:
                        # 検出失敗時も contract (len==33) を守るためゼロ埋めで返す
                        landmarks_list = [
                            {"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}
                            for _ in range(33)
                        ]

                    # Phase A: side は 'a' 固定。将来 bbox と突合して 'a'/'b' 振り分け予定。
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

        return samples
