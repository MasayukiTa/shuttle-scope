"""YOLOv8n-pose ONNX 推論による Pose 推定。

MediaPipe の代替として ONNX Runtime CUDA / TensorRT EP で動作し、
大幅に高速な姿勢推定を実現する。

出力形式:
    COCO 17 keypoints を MediaPipe 33 点互換フォーマットにマッピングして
    PoseSample として返す。gravity.py が使う landmarks[-2/-1] (足首) は
    COCO 15/16 を 31/32 スロットに配置することで互換を維持する。

COCO 17 → MediaPipe 33 主要マッピング:
    coco[0] nose            → mp[0]
    coco[5] left shoulder   → mp[11]
    coco[6] right shoulder  → mp[12]
    coco[7] left elbow      → mp[13]
    coco[8] right elbow     → mp[14]
    coco[9] left wrist      → mp[15]
    coco[10] right wrist    → mp[16]
    coco[11] left hip       → mp[23]
    coco[12] right hip      → mp[24]
    coco[13] left knee      → mp[25]
    coco[14] right knee     → mp[26]
    coco[15] left ankle     → mp[27] & mp[31]  (gravity 用に両スロット)
    coco[16] right ankle    → mp[28] & mp[32]  (gravity 用に両スロット)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

import cv2
import numpy as np

from backend.cv.base import PoseSample

logger = logging.getLogger(__name__)

# COCO 17 keypoint インデックス → MediaPipe 33 スロット
_COCO_TO_MP: dict[int, list[int]] = {
    0:  [0],        # nose
    1:  [2],        # left eye
    2:  [5],        # right eye
    3:  [7],        # left ear
    4:  [8],        # right ear
    5:  [11],       # left shoulder
    6:  [12],       # right shoulder
    7:  [13],       # left elbow
    8:  [14],       # right elbow
    9:  [15],       # left wrist
    10: [16],       # right wrist
    11: [23],       # left hip
    12: [24],       # right hip
    13: [25],       # left knee
    14: [26],       # right knee
    15: [27, 31],   # left ankle → mp[27] 通常スロット & mp[31] gravity 用
    16: [28, 32],   # right ankle → mp[28] 通常スロット & mp[32] gravity 用
}

_MODELS_DIR = Path(__file__).parent.parent / "models"
_FP16_MODEL = _MODELS_DIR / "yolov8n_pose_fp16.onnx"
_FP32_MODEL = _MODELS_DIR / "yolov8n_pose.onnx"

_CONF_THRESH = 0.25
_IOU_THRESH = 0.45
_MODEL_H, _MODEL_W = 384, 640


def _coco_kpts_to_mp33(kpts: np.ndarray, img_h: int, img_w: int) -> list[dict]:
    """COCO 17 keypoints (17, 3) → MediaPipe 33 互換 landmark リスト。"""
    mp = [{"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}] * 33
    mp = [dict(d) for d in mp]  # mutable copies
    for ci, mp_slots in _COCO_TO_MP.items():
        x_norm = float(kpts[ci, 0]) / img_w
        y_norm = float(kpts[ci, 1]) / img_h
        vis = float(kpts[ci, 2])
        for si in mp_slots:
            mp[si] = {"x": x_norm, "y": y_norm, "z": 0.0, "visibility": vis}
    return mp


def _preprocess_batch(frames: list[np.ndarray], dtype=np.float32) -> np.ndarray:
    """BGR フレームリスト → モデル入力テンソル (N, 3, H, W)。dtype はモデル IO に合わせる。"""
    out = np.empty((len(frames), 3, _MODEL_H, _MODEL_W), dtype=dtype)
    for i, f in enumerate(frames):
        resized = cv2.resize(f, (_MODEL_W, _MODEL_H))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(dtype) / dtype(255)
        out[i] = rgb.transpose(2, 0, 1)
    return out


def _nms(boxes: np.ndarray, scores: np.ndarray) -> list[int]:
    """シンプル NMS (IoU ベース)。"""
    if len(scores) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0, xx2 - xx1 + 1)
        h = np.maximum(0, yy2 - yy1 + 1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[1:][iou <= _IOU_THRESH]
    return keep


def _decode_output(
    raw: np.ndarray,  # (56, N) or (N, 56)
    orig_h: int, orig_w: int,
    img_h: int = _MODEL_H, img_w: int = _MODEL_W,
) -> list[np.ndarray] | None:
    """YOLO pose ONNX 出力 → COCO keypoints リスト (1 フレーム最大 2 人)。

    返り値: [(17, 3), ...] の keypoints 配列リスト。検出なしは None。
    """
    # 出力が (56, N) なら転置
    if raw.shape[0] == 56:
        raw = raw.T  # (N, 56)
    raw = raw.astype(np.float32)

    scores = raw[:, 4]
    mask = scores > _CONF_THRESH
    if not mask.any():
        return None

    raw = raw[mask]
    scores = scores[mask]

    # cxcywh → xyxy (モデル入力サイズ空間)
    cx, cy, bw, bh = raw[:, 0], raw[:, 1], raw[:, 2], raw[:, 3]
    x1 = cx - bw / 2; y1 = cy - bh / 2
    x2 = cx + bw / 2; y2 = cy + bh / 2
    boxes = np.stack([x1, y1, x2, y2], axis=1)

    keep = _nms(boxes, scores)
    # 最大 2 人 (a / b 両選手)
    keep = keep[:2]

    # スケールをオリジナル画像サイズに変換
    sx = orig_w / img_w
    sy = orig_h / img_h

    results = []
    for idx in keep:
        kpts_flat = raw[idx, 5:]  # 17*3 = 51
        kpts = kpts_flat.reshape(17, 3)
        kpts[:, 0] *= sx  # x pixel
        kpts[:, 1] *= sy  # y pixel
        results.append(kpts)
    return results or None


class OnnxPose:
    """YOLOv8n-pose ONNX を使った高速 Pose 推論。

    インタフェースは CpuPose / CudaPose と同一: run(video_path) → List[PoseSample]。
    """

    def __init__(
        self,
        model_path: Path | None = None,
        device_index: int = 0,
        use_trt: bool = False,
        inference_batch: int = 16,
    ) -> None:
        self._device_index = device_index
        self._inference_batch = inference_batch
        self._sess = None
        self._input_name: str = "images"
        self._in_dtype = np.float16
        self._backend = "unloaded"
        self._model_path = model_path or (_FP16_MODEL if _FP16_MODEL.exists() else _FP32_MODEL)
        self._use_trt = use_trt
        self._load()

    def _trt_cache_dir(self) -> str:
        return str(self._model_path.parent / "trt_cache")

    def _load(self) -> None:
        try:
            import onnxruntime as ort
        except ImportError:
            raise RuntimeError("onnxruntime 未インストール")

        if not self._model_path.exists():
            raise RuntimeError(f"Pose モデルが見つかりません: {self._model_path}")

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.enable_mem_pattern = True
        so.enable_mem_reuse = True

        # 入力 dtype を ONNX メタから自動判定
        probe = ort.InferenceSession(str(self._model_path), providers=["CPUExecutionProvider"])
        self._input_name = probe.get_inputs()[0].name
        self._in_dtype = (
            np.float16 if "float16" in probe.get_inputs()[0].type else np.float32
        )
        del probe

        avail = ort.get_available_providers()

        # TensorRT EP: nvinfer_10.dll がある場合のみ試みる
        _trt_ok = self._use_trt and "TensorrtExecutionProvider" in avail
        if _trt_ok:
            try:
                import ctypes; ctypes.WinDLL("nvinfer_10.dll")
            except OSError:
                _trt_ok = False
        if _trt_ok:
            trt_dir = self._trt_cache_dir()
            os.makedirs(trt_dir, exist_ok=True)
            trt_opts: dict = {
                "device_id": self._device_index,
                "trt_fp16_enable": True,
                "trt_engine_cache_enable": True,
                "trt_engine_cache_path": trt_dir,
                "trt_max_workspace_size": 2 * 1024 ** 3,
                "trt_profile_min_shapes": f"{self._input_name}:1x3x{_MODEL_H}x{_MODEL_W}",
                "trt_profile_opt_shapes": f"{self._input_name}:{self._inference_batch}x3x{_MODEL_H}x{_MODEL_W}",
                "trt_profile_max_shapes": f"{self._input_name}:64x3x{_MODEL_H}x{_MODEL_W}",
            }
            cuda_opts: dict = {
                "device_id": self._device_index,
                "cudnn_conv_algo_search": "HEURISTIC",
                "arena_extend_strategy": "kNextPowerOfTwo",
            }
            providers = [
                ("TensorrtExecutionProvider", trt_opts),
                ("CUDAExecutionProvider", cuda_opts),
                "CPUExecutionProvider",
            ]
            try:
                self._sess = ort.InferenceSession(
                    str(self._model_path), sess_options=so, providers=providers
                )
                self._backend = f"trt:{self._device_index}"
                logger.info("OnnxPose loaded via TensorRT (device=%d, model=%s)",
                            self._device_index, self._model_path.name)
                return
            except Exception as exc:
                logger.warning("OnnxPose TRT 初期化失敗: %s — CUDA EP にフォールバック", exc)

        # CUDA EP
        if "CUDAExecutionProvider" in avail:
            cuda_opts = {
                "device_id": self._device_index,
                "cudnn_conv_algo_search": "HEURISTIC",
                "arena_extend_strategy": "kNextPowerOfTwo",
                "do_copy_in_default_stream": "1",
            }
            providers = [
                ("CUDAExecutionProvider", cuda_opts),
                "CPUExecutionProvider",
            ]
            try:
                self._sess = ort.InferenceSession(
                    str(self._model_path), sess_options=so, providers=providers
                )
                self._backend = f"cuda:{self._device_index}"
                logger.info("OnnxPose loaded via CUDA EP (device=%d, model=%s)",
                            self._device_index, self._model_path.name)
                return
            except Exception as exc:
                logger.warning("OnnxPose CUDA EP 初期化失敗: %s — CPU にフォールバック", exc)

        # CPU fallback
        self._sess = ort.InferenceSession(
            str(self._model_path), sess_options=so, providers=["CPUExecutionProvider"]
        )
        self._backend = "cpu"
        logger.info("OnnxPose loaded via CPU EP (model=%s)", self._model_path.name)

    def backend_name(self) -> str:
        return self._backend

    def run(self, video_path: str) -> List[PoseSample]:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []

        fps_src = cap.get(cv2.CAP_PROP_FPS) or 30.0
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or _MODEL_W
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or _MODEL_H

        frames_buf: list[np.ndarray] = []
        frame_indices: list[int] = []
        idx = 0
        results: List[PoseSample] = []

        def _infer_batch(buf: list[np.ndarray], idxs: list[int]) -> None:
            batch = _preprocess_batch(buf, self._in_dtype)
            raw_out = self._sess.run(None, {self._input_name: batch})
            # raw_out[0] shape: (batch, 56, N) or (batch, N, 56)
            out = raw_out[0]
            for bi, fi in enumerate(idxs):
                ts = fi / fps_src
                detections = _decode_output(out[bi], orig_h, orig_w)
                if detections is None:
                    # 検出なし: 33-point のゼロランドマーク
                    mp = [{"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}] * 33
                    results.append(PoseSample(frame=fi, ts_sec=ts, side="a", landmarks=mp))
                    continue
                sides = ["a", "b"]
                for di, kpts in enumerate(detections):
                    mp = _coco_kpts_to_mp33(kpts, orig_h, orig_w)
                    results.append(PoseSample(
                        frame=fi, ts_sec=ts,
                        side=sides[di] if di < len(sides) else "b",
                        landmarks=mp,
                    ))

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frames_buf.append(frame)
            frame_indices.append(idx)
            idx += 1
            if len(frames_buf) >= self._inference_batch:
                _infer_batch(frames_buf, frame_indices)
                frames_buf.clear()
                frame_indices.clear()

        if frames_buf:
            _infer_batch(frames_buf, frame_indices)

        cap.release()
        return results

    def run_frames(self, frames: list[np.ndarray]) -> List[PoseSample]:
        """フレームリスト直接入力版。ベンチマーク計測用。"""
        orig_h, orig_w = frames[0].shape[:2] if frames else (_MODEL_H, _MODEL_W)
        results: List[PoseSample] = []
        for start in range(0, len(frames), self._inference_batch):
            buf = frames[start: start + self._inference_batch]
            batch = _preprocess_batch(buf, self._in_dtype)
            raw_out = self._sess.run(None, {self._input_name: batch})
            out = raw_out[0]
            for bi in range(len(buf)):
                fi = start + bi
                detections = _decode_output(out[bi], orig_h, orig_w)
                sides = ["a", "b"]
                if detections is None:
                    mp = [{"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}] * 33
                    results.append(PoseSample(frame=fi, ts_sec=fi / 30.0, side="a", landmarks=mp))
                    continue
                for di, kpts in enumerate(detections):
                    mp = _coco_kpts_to_mp33(kpts, orig_h, orig_w)
                    results.append(PoseSample(
                        frame=fi, ts_sec=fi / 30.0,
                        side=sides[di] if di < len(sides) else "b",
                        landmarks=mp,
                    ))
        return results
