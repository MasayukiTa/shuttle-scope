"""ベンチマーク用合成データ生成ユーティリティ。

make_frames()  : numpy フレームリストを生成（LRU キャッシュ付き）
make_video_file(): clip_extract ベンチ用の合成 mp4 を生成
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from functools import lru_cache
from typing import List

import numpy as np

logger = logging.getLogger(__name__)

# フレームサイズのデフォルト値
_DEFAULT_W = 1920
_DEFAULT_H = 1080


@lru_cache(maxsize=8)
def make_frames(n: int, width: int = _DEFAULT_W, height: int = _DEFAULT_H) -> List[np.ndarray]:
    """合成フレームを n 枚生成して返す（同一引数は再計算しない）。

    緑コート背景にランダムノイズを重ねた uint8 BGR 画像を生成する。
    乱数シードを固定して決定的にする。
    """
    rng = np.random.default_rng(42)
    # 緑コート基調（BGR: 40, 120, 40）
    base = np.full((height, width, 3), [40, 120, 40], dtype=np.uint8)
    frames: List[np.ndarray] = []
    for _ in range(n):
        noise = rng.integers(0, 60, (height, width, 3), dtype=np.uint8)
        frame = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        frames.append(frame)
    logger.debug("[synthetic] %d フレーム生成完了 (%dx%d)", n, width, height)
    return frames


def make_video_file(n: int = 90, fps: int = 30, path: str | None = None) -> str:
    """合成フレームから mp4 ファイルを生成して返す（clip_extract ベンチ用）。

    path が None の場合は一時ファイルを生成する（呼び出し元が削除すること）。
    ffmpeg が使用不可な場合は RuntimeError を送出する。
    """
    # ffmpeg の存在確認
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError("ffmpeg が利用できません")
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg がインストールされていません") from exc

    # 出力パス決定
    if path is None:
        fd, path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)

    frames = make_frames(n, _DEFAULT_W, _DEFAULT_H)

    # ffmpeg に rawvideo でパイプ渡し
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{_DEFAULT_W}x{_DEFAULT_H}",
        "-r", str(fps),
        "-i", "pipe:0",
        "-an",
        "-vcodec", "libx264",
        "-preset", "ultrafast",
        "-crf", "35",
        path,
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for frame in frames:
        assert proc.stdin is not None
        proc.stdin.write(frame.tobytes())
    assert proc.stdin is not None
    proc.stdin.close()
    proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 終了コード {proc.returncode}: 合成動画生成失敗")

    logger.debug("[synthetic] 合成 mp4 生成: %s (%d フレーム, %d fps)", path, n, fps)
    return path
