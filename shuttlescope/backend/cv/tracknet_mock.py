"""決定的ダミー TrackNet 実装。

テスト / 非 CUDA 環境 (SS_CV_MOCK=1) 用。torch 等に依存しない。
動画長が不明な場合でも 30 秒 × 30fps = 900 frame のダミー軌跡を返す。
"""
from __future__ import annotations

import math
import os
from typing import List

from backend.cv.base import ShuttleSample, TrackNetInferencer


class MockTrackNet(TrackNetInferencer):
    """sin 波を描くダミーのシャトル軌跡を返すだけの実装。

    - 決定的 (同じ video_path → 同じ出力) にして比較テストを容易にする。
    - 動画の物理的な長さは参照しない。ファイル存在有無にも依存しない。
    """

    def __init__(self, fps: int = 30, duration_sec: float = 30.0) -> None:
        self._fps = fps
        self._duration_sec = duration_sec

    def run(self, video_path: str) -> List[ShuttleSample]:
        # 動画パスのハッシュで位相をずらし、複数動画のダミーも区別できるようにする
        phase = float(abs(hash(os.path.basename(video_path))) % 360) * math.pi / 180.0

        total_frames = int(self._fps * self._duration_sec)
        samples: List[ShuttleSample] = []
        for i in range(total_frames):
            ts = i / float(self._fps)
            # コート中央 (640, 360) 付近を sin 波で揺らすダミー
            x = 640.0 + 200.0 * math.sin(phase + ts * 2.0 * math.pi / 3.0)
            y = 360.0 + 120.0 * math.sin(phase + ts * 2.0 * math.pi / 1.5)
            samples.append(
                ShuttleSample(frame=i, ts_sec=ts, x=x, y=y, confidence=0.8)
            )
        return samples
