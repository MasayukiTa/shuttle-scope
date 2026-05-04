"""CpuTrackNet の基本動作テスト。

GPU 無し (i5-1235U / CUDA 無し) 環境でも通ることを絶対要件とする。
"""
from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from backend.cv.base import ShuttleSample
from backend.cv.tracknet_cpu import CpuTrackNet


def _write_dummy_video(path: str, num_frames: int = 30, size=(320, 240), fps: int = 30) -> None:
    """白いシャトルが移動するダミー動画を生成する。"""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, size)
    try:
        w, h = size
        for i in range(num_frames):
            # 背景: 緑っぽいコート
            frame = np.full((h, w, 3), (30, 80, 30), dtype=np.uint8)
            # シャトル: 白い小円を左→右に動かす
            cx = int(20 + (w - 40) * (i / max(num_frames - 1, 1)))
            cy = int(h / 2 + 10 * np.sin(i * 0.3))
            cv2.circle(frame, (cx, cy), 6, (240, 240, 240), -1)
            writer.write(frame)
    finally:
        writer.release()


def test_cpu_tracknet_returns_sample_per_frame(tmp_path):
    video_path = str(tmp_path / "dummy.mp4")
    _write_dummy_video(video_path, num_frames=30)
    assert os.path.exists(video_path)

    samples = CpuTrackNet().run(video_path)

    # 30 フレーム入れたので 30 サンプル返る。
    assert len(samples) == 30
    for s in samples:
        assert isinstance(s, ShuttleSample)
        # 必須フィールドが存在すること。
        assert hasattr(s, "confidence")
        assert 0.0 <= s.confidence <= 1.0
        assert isinstance(s.frame, int)
        assert isinstance(s.ts_sec, float)
        assert isinstance(s.x, float)
        assert isinstance(s.y, float)


def test_cpu_tracknet_missing_video_raises(tmp_path):
    missing = str(tmp_path / "does_not_exist.mp4")
    with pytest.raises(RuntimeError):
        CpuTrackNet().run(missing)
