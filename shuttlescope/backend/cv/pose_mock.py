"""決定的ダミー Pose 実装 (MediaPipe 非依存)。"""
from __future__ import annotations

import os
from typing import List

from backend.cv.base import PoseInferencer, PoseSample


class MockPose(PoseInferencer):
    """両選手分のダミー姿勢サンプルを返す。

    landmarks は 33 点ぶんの (x, y, z, visibility) を均等な float で埋める。
    """

    def __init__(self, fps: int = 30, duration_sec: float = 30.0) -> None:
        self._fps = fps
        self._duration_sec = duration_sec

    def run(self, video_path: str) -> List[PoseSample]:
        _ = os.path.basename(video_path)  # 参照のみ
        total_frames = int(self._fps * self._duration_sec)
        samples: List[PoseSample] = []
        for i in range(total_frames):
            ts = i / float(self._fps)
            for side in ("a", "b"):
                # 33 点のダミー landmarks
                landmarks = [
                    {"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.9}
                    for _ in range(33)
                ]
                samples.append(
                    PoseSample(frame=i, ts_sec=ts, side=side, landmarks=landmarks)
                )
        return samples
