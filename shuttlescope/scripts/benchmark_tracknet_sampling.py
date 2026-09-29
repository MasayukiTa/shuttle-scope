"""Benchmark TrackNet video sampling without writing ShuttleScope DB state.

Run from the shuttlescope directory, for example:
  python scripts/benchmark_tracknet_sampling.py VIDEO.mp4 --sample-fps 15 30 --max-seconds 60
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2

from backend.tracknet.inference import get_inference
from backend.tracknet.video_sampling import TrackNetFrameSampler, step_frames_for_fps


def _run_one(
    inf,
    video: Path,
    sample_fps: float,
    max_seconds: float | None,
    window_batch: int = 4,
) -> dict:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_sec = total_frames / fps if total_frames > 0 else 0.0
    frame_limit = total_frames if total_frames > 0 else None
    if max_seconds is not None and max_seconds > 0:
        requested = max(3, int(round(max_seconds * fps)))
        frame_limit = requested if frame_limit is None else min(frame_limit, requested)

    step_frames = step_frames_for_fps(fps, sample_fps)
    sampler = TrackNetFrameSampler(step_frames=step_frames)
    confidences: list[float] = []
    detections = 0
    inference_seconds = 0.0
    result_count = 0

    preferred_batch = inf.preferred_window_batch_size()
    effective_window_batch = max(1, min(int(window_batch), preferred_batch))
    pending_windows = []

    def flush_pending() -> None:
        nonlocal detections, inference_seconds, result_count
        if not pending_windows:
            return
        t0 = time.perf_counter()
        results = inf.predict_windows([sampled.frames for sampled in pending_windows])
        inference_seconds += time.perf_counter() - t0
        if len(results) != len(pending_windows):
            raise RuntimeError(
                f"TrackNet returned {len(results)} results for "
                f"{len(pending_windows)} sampled windows"
            )
        for result in results:
            result_count += 1
            conf = float(result.get("confidence") or 0.0)
            confidences.append(conf)
            if result.get("x_norm") is not None and result.get("y_norm") is not None:
                detections += 1
        pending_windows.clear()

    wall_start = time.perf_counter()
    try:
        while True:
            if frame_limit is not None and sampler.decoded_frames >= frame_limit:
                break
            ok, frame = cap.read()
            if not ok:
                break

            sampled = sampler.push(frame)
            if sampled is None:
                continue

            pending_windows.append(sampled)
            if len(pending_windows) >= effective_window_batch:
                flush_pending()
        flush_pending()
    finally:
        cap.release()

    wall_seconds = time.perf_counter() - wall_start
    source_seconds = sampler.decoded_frames / fps if fps > 0 else 0.0
    full_projection = None
    if source_seconds > 0 and duration_sec > 0:
        full_projection = wall_seconds * duration_sec / source_seconds

    return {
        "requested_sample_fps": sample_fps,
        "effective_sample_fps": round(fps / step_frames, 4),
        "step_frames": step_frames,
        "window_batch": effective_window_batch,
        "preferred_window_batch": preferred_batch,
        "video_fps": round(fps, 4),
        "video_total_frames": total_frames,
        "video_duration_sec": round(duration_sec, 3),
        "bench_source_sec": round(source_seconds, 3),
        "decoded_frames": sampler.decoded_frames,
        "sampled_windows": sampler.sampled_windows,
        "result_count": result_count,
        "detections": detections,
        "detection_rate": round(detections / result_count, 4) if result_count else 0.0,
        "confidence_mean": round(statistics.mean(confidences), 4) if confidences else 0.0,
        "confidence_median": round(statistics.median(confidences), 4) if confidences else 0.0,
        "wall_seconds": round(wall_seconds, 3),
        "inference_seconds": round(inference_seconds, 3),
        "decode_overhead_seconds": round(max(0.0, wall_seconds - inference_seconds), 3),
        "realtime_factor": round(wall_seconds / source_seconds, 4) if source_seconds else None,
        "projected_full_seconds": round(full_projection, 3) if full_projection is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--sample-fps", type=float, nargs="+", default=[15.0, 30.0])
    parser.add_argument("--max-seconds", type=float, default=60.0)
    parser.add_argument("--backend", default="auto")
    parser.add_argument(
        "--window-batch",
        type=int,
        default=4,
        help="independent sampled windows per inference call (default: 4)",
    )
    args = parser.parse_args()

    if not args.video.is_file():
        raise SystemExit(f"video not found: {args.video}")

    load_start = time.perf_counter()
    inf = get_inference(args.backend)
    if not inf.load():
        raise SystemExit(inf.get_load_error() or "TrackNet backend load failed")
    load_seconds = time.perf_counter() - load_start

    runs = [
        _run_one(inf, args.video, sample_fps, args.max_seconds, args.window_batch)
        for sample_fps in args.sample_fps
    ]
    report = {
        "video": str(args.video),
        "backend": inf.backend_name(),
        "model_load_seconds": round(load_seconds, 3),
        "runs": runs,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
