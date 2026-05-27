"""PersonTracker.update vs update_batch fps 比較ベンチ。

動画から N frame をまとめて取得し:
  - 旧 update(frame) を 1 フレームずつ呼ぶ (host overhead 含む)
  - 新 update_batch(frames, idxs) で batch=B でまとめて検出
それぞれの **end-to-end fps** を測る (decode + preprocess + infer + ByteTrack + court adjudicate)。
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from pathlib import Path

# repo root を sys.path へ
_HERE = Path(__file__).resolve()
_REPO = _HERE.parent.parent  # shuttlescope/
sys.path.insert(0, str(_REPO))

# tensorrt_libs DLL 登録 (ORT が見つけられるように)
try:
    import torch  # noqa: F401
    os.add_dll_directory(os.path.join(os.path.dirname(__import__("torch").__file__), "lib"))
except Exception:
    pass
try:
    import tensorrt_libs  # type: ignore
    os.add_dll_directory(os.path.dirname(tensorrt_libs.__file__))
except Exception:
    pass

import cv2
import numpy as np

from backend.cv.person_tracker import PersonTracker  # noqa: E402


def load_frames(video: Path, start_sec: float, n: int) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(video))
    fps_v = cap.get(cv2.CAP_PROP_FPS) or 60
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(start_sec * fps_v))
    frames: list[np.ndarray] = []
    for _ in range(n):
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    return frames


def bench_single(frames: list, match_id: int | None) -> tuple[float, int]:
    tracker = PersonTracker(match_type="doubles", match_id=match_id)
    # warmup
    for i in range(3):
        tracker.update(frames[0], i)
    # ID accumulation を防ぐためリセット
    if hasattr(tracker, "_tracker") and tracker._tracker is not None:
        try:
            tracker._tracker.reset()
        except Exception:
            pass
    t0 = time.perf_counter()
    n_tracks_total = 0
    for i, f in enumerate(frames):
        tracks = tracker.update(f, i)
        n_tracks_total += len(tracks)
    dt = time.perf_counter() - t0
    return len(frames) / dt, n_tracks_total


def bench_batch(frames: list, batch: int, match_id: int | None) -> tuple[float, int]:
    tracker = PersonTracker(match_type="doubles", match_id=match_id)
    # 検出器を遅延 init するため warmup
    tracker._ensure_batch_detector()
    if tracker._batch_sess is None:
        print(f"  batch={batch}: batch detector init failed, skip")
        return 0.0, 0
    # warmup
    tracker._detect_batch(frames[:batch])
    if hasattr(tracker, "_tracker") and tracker._tracker is not None:
        try:
            tracker._tracker.reset()
        except Exception:
            pass

    t0 = time.perf_counter()
    n_tracks_total = 0
    i = 0
    while i < len(frames):
        chunk = frames[i : i + batch]
        idxs = list(range(i, i + len(chunk)))
        out = tracker.update_batch(chunk, idxs)
        for tracks in out:
            n_tracks_total += len(tracks)
        i += batch
    dt = time.perf_counter() - t0
    return len(frames) / dt, n_tracks_total


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True, type=Path)
    p.add_argument("--start-sec", type=float, default=120)
    p.add_argument("--n", type=int, default=240)  # 4 秒分 (@ 60 fps)
    p.add_argument("--match-id", type=int, default=None)
    args = p.parse_args()

    frames = load_frames(args.video, args.start_sec, args.n)
    print(f"loaded {len(frames)} frames")
    if not frames:
        return 1

    print("\n=== single-frame mode ===")
    fps, n_t = bench_single(frames, args.match_id)
    print(f"  update(frame) loop : {fps:6.1f} fps  ({n_t} total tracks)")

    print("\n=== batch mode ===")
    for b in [4, 8, 16, 32]:
        fps, n_t = bench_batch(frames, b, args.match_id)
        print(f"  update_batch({b:2d}) : {fps:6.1f} fps  ({n_t} total tracks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
