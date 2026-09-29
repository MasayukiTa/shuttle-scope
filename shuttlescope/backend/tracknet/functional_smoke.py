"""Functional TrackNet checkpoint/ONNX parity smoke against upstream test video.

This is intentionally separate from the production dependency set. It runs in
TrackNet Smoke CI where TensorFlow 2.15 and ONNX Runtime are installed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

_POSITIVE_FRAMES = (2, 5, 10, 20)
_THRESHOLD = 0.5


def _load_frames(video: Path, through_frame: int) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video}")
    frames: list[np.ndarray] = []
    try:
        for _ in range(through_frame + 1):
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
    finally:
        cap.release()
    if len(frames) <= through_frame:
        raise RuntimeError(
            f"video ended at frame {len(frames) - 1}, need frame {through_frame}"
        )
    return frames


def _upstream_input(frames: list[np.ndarray], target_frame: int) -> np.ndarray:
    """Reproduce upstream predict.py exactly for [t-2, t-1, t]."""
    gray_stack = []
    for idx in (target_frame - 2, target_frame - 1, target_frame):
        gray = cv2.cvtColor(frames[idx], cv2.COLOR_BGR2GRAY)
        gray_stack.append(np.expand_dims(gray, axis=2))
    joined = np.concatenate(gray_stack, axis=2)
    resized = cv2.resize(joined, (512, 288))
    chw = np.moveaxis(resized, -1, 0)
    return np.expand_dims(chw, axis=0).astype(np.float32) / 255.0


def _max_confidences_tf(model, inputs: list[np.ndarray]) -> tuple[list[float], list[np.ndarray]]:
    confs: list[float] = []
    outputs: list[np.ndarray] = []
    for inp in inputs:
        out = model(inp, training=False).numpy()[0, 0]
        outputs.append(out)
        confs.append(float(out.max()))
    return confs, outputs


def _max_confidences_onnx(path: Path, inputs: list[np.ndarray]) -> tuple[list[float], list[np.ndarray]]:
    import onnxruntime as ort

    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    confs: list[float] = []
    outputs: list[np.ndarray] = []
    for inp in inputs:
        out = sess.run(None, {input_name: inp})[0][0, 0]
        outputs.append(out)
        confs.append(float(out.max()))
    return confs, outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("backend/tracknet/weights/TrackNet"),
    )
    parser.add_argument(
        "--onnx",
        type=Path,
        default=Path("backend/tracknet/weights/tracknet.onnx"),
    )
    args = parser.parse_args()

    import tensorflow as tf  # noqa: F401
    from backend.tracknet.model import build_tracknet_model

    frames = _load_frames(args.video, max(_POSITIVE_FRAMES))
    inputs = [_upstream_input(frames, target) for target in _POSITIVE_FRAMES]

    model = build_tracknet_model()
    status = model.load_weights(str(args.checkpoint))

    restore_error = None
    try:
        status.assert_existing_objects_matched()
    except AssertionError as exc:
        restore_error = str(exc)

    consumed_error = None
    try:
        status.assert_consumed()
    except AssertionError as exc:
        consumed_error = str(exc)

    tf_conf, tf_outputs = _max_confidences_tf(model, inputs)
    onnx_conf, onnx_outputs = _max_confidences_onnx(args.onnx, inputs)
    max_abs_diff = max(
        float(np.max(np.abs(a - b)))
        for a, b in zip(tf_outputs, onnx_outputs)
    )

    report = {
        "positive_frames": list(_POSITIVE_FRAMES),
        "threshold": _THRESHOLD,
        "restore_existing_objects_matched": restore_error is None,
        "restore_existing_objects_error": restore_error,
        "restore_consumed": consumed_error is None,
        "restore_consumed_error": consumed_error,
        "tensorflow_max_confidences": [round(v, 6) for v in tf_conf],
        "onnx_max_confidences": [round(v, 6) for v in onnx_conf],
        "tensorflow_detections": sum(v >= _THRESHOLD for v in tf_conf),
        "onnx_detections": sum(v >= _THRESHOLD for v in onnx_conf),
        "tf_onnx_max_abs_diff": max_abs_diff,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    errors: list[str] = []
    if restore_error is not None:
        errors.append("checkpoint restore did not match all existing model objects")
    if max(tf_conf, default=0.0) < _THRESHOLD:
        errors.append("TensorFlow checkpoint produced no >=0.5 positive detection")
    if max(onnx_conf, default=0.0) < _THRESHOLD:
        errors.append("exported ONNX produced no >=0.5 positive detection")
    if max_abs_diff > 1e-3:
        errors.append(f"TensorFlow/ONNX output drift too large: {max_abs_diff:.6g}")

    if errors:
        raise RuntimeError("; ".join(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
