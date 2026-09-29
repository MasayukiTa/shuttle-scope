"""CpuPose (MediaPipe Solutions API, CPU) の本実装テスト。

mediapipe / cv2 / numpy が揃っていない環境では skip する。
CI や純粋な backend 起動テストを壊さないよう、インポートは関数/fixture 内で行う。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


# mediapipe / cv2 / numpy のいずれか欠けていればモジュール全体を skip
mediapipe = pytest.importorskip("mediapipe")
cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


@pytest.fixture(scope="module")
def dummy_video_path() -> str:
    """30 フレームのダミー mp4 を生成する fixture。

    単色グラデーションで人物は映らないが、CpuPose は検出失敗時にもゼロ埋めで
    33 点返す契約のため、テストとしては len(samples) と landmarks 長だけ検証する。
    """
    tmp_dir = tempfile.mkdtemp(prefix="ss_pose_cpu_test_")
    video_path = Path(tmp_dir) / "dummy.mp4"

    width, height, fps = 160, 120, 30
    total_frames = 30

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, fps, (width, height))
    if not writer.isOpened():
        pytest.skip("cv2.VideoWriter が mp4v codec を開けませんでした")

    try:
        for i in range(total_frames):
            # 単純なグラデーションフレーム (BGR)
            frame = np.full((height, width, 3), fill_value=(i * 8) % 256, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()

    # 実際に書き出せたか確認 (一部 Windows 環境では codec 無効で失敗する)
    if not video_path.exists() or video_path.stat().st_size == 0:
        pytest.skip("ダミー mp4 の書き出しに失敗しました (codec 不足の可能性)")

    yield str(video_path)

    try:
        os.remove(video_path)
        os.rmdir(tmp_dir)
    except OSError:
        pass


def test_cpu_pose_returns_33_landmarks_per_frame(dummy_video_path: str) -> None:
    """30 フレーム動画に対し 30 件のサンプル、各 33 ランドマークが返ることを検証。"""
    from backend.cv.pose_cpu import CpuPose

    pose = CpuPose()
    samples = pose.run(dummy_video_path)

    # フレーム数一致 (多少の codec 差を許容して >=29 も許容)
    assert len(samples) >= 29, f"期待: 30 フレーム前後, 実際: {len(samples)}"
    assert len(samples) <= 31

    for s in samples:
        assert len(s.landmarks) == 33, "MediaPipe Pose の 33 ランドマーク契約"
        # 各 landmark は x/y/z/visibility を持つ dict
        for lm in s.landmarks:
            assert set(lm.keys()) >= {"x", "y", "z", "visibility"}
        assert s.side in ("a", "b")
