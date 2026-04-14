"""リアルタイム YOLO (yolov8n) 推論モジュール

ブラウザ中継のオペレーター PC 側で、受信 MediaStream から送られてくる
JPEG フレームに対して person 検出を 55fps+ 目標で行うための軽量モジュール。

重処理バッチ YOLO (`backend/routers/yolo.py`) とは独立に動作する。モデル未配置時は
`is_available()` が False を返し、ルータ側で接続を拒否する。
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import List

import cv2
import numpy as np

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "yolov8n.onnx")
_INPUT_W = 640
_INPUT_H = 384
_CONF_TH = 0.35
_IOU_TH = 0.45
_PERSON_CLS = 0  # COCO class 0 = person

_session = None
_lock = threading.Lock()
_load_attempted = False


def _try_load() -> None:
    global _session, _load_attempted
    if _load_attempted:
        return
    _load_attempted = True
    path = os.path.abspath(_MODEL_PATH)
    if not os.path.exists(path):
        return
    try:
        import onnxruntime as ort  # 遅延 import
        providers = ["CPUExecutionProvider"]
        _session = ort.InferenceSession(path, providers=providers)
        print(f"[realtime-yolo] YOLOv8n ONNX loaded: {path}")
    except Exception as e:  # pragma: no cover
        print(f"[realtime-yolo] failed to load {path}: {e}")
        _session = None


def is_available() -> bool:
    with _lock:
        _try_load()
        return _session is not None


@dataclass
class Detection:
    x1: float  # 正規化 [0,1]
    y1: float
    x2: float
    y2: float
    conf: float


def _letterbox(img: np.ndarray) -> tuple[np.ndarray, float, int, int]:
    h, w = img.shape[:2]
    r = min(_INPUT_W / w, _INPUT_H / h)
    nw, nh = int(round(w * r)), int(round(h * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((_INPUT_H, _INPUT_W, 3), 114, dtype=np.uint8)
    dx = (_INPUT_W - nw) // 2
    dy = (_INPUT_H - nh) // 2
    canvas[dy:dy + nh, dx:dx + nw] = resized
    return canvas, r, dx, dy


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_th: float) -> List[int]:
    if len(boxes) == 0:
        return []
    idxs = cv2.dnn.NMSBoxes(
        bboxes=[[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes],
        scores=scores.tolist(),
        score_threshold=_CONF_TH,
        nms_threshold=iou_th,
    )
    if isinstance(idxs, tuple) or len(idxs) == 0:
        return []
    return [int(i) for i in np.array(idxs).flatten()]


def infer_jpeg(jpeg_bytes: bytes) -> List[Detection]:
    """JPEG バイト列を推論し、person の正規化 bbox リストを返す。

    モデル未配置または推論失敗時は空リスト。
    """
    with _lock:
        _try_load()
        if _session is None:
            return []
        session = _session

    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return []
    orig_h, orig_w = img.shape[:2]

    canvas, r, dx, dy = _letterbox(img)
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    tensor = rgb.astype(np.float32).transpose(2, 0, 1)[None] / 255.0

    try:
        outputs = session.run(None, {session.get_inputs()[0].name: tensor})
    except Exception:
        return []
    pred = outputs[0]

    # ultralytics yolov8 ONNX は (1, 84, N) を返す。他形状も一応 flip 対応。
    if pred.ndim == 3 and pred.shape[1] < pred.shape[2]:
        # (1, 84, N) → (N, 84)
        pred = pred[0].T
    elif pred.ndim == 3:
        pred = pred[0]
    else:
        return []

    # 各行: [cx, cy, w, h, cls0_score, cls1_score, ..., cls79_score]
    if pred.shape[1] < 5:
        return []
    class_scores = pred[:, 4:]
    cls_ids = np.argmax(class_scores, axis=1)
    cls_conf = class_scores[np.arange(len(pred)), cls_ids]
    mask = (cls_ids == _PERSON_CLS) & (cls_conf >= _CONF_TH)
    if not np.any(mask):
        return []
    pred = pred[mask]
    cls_conf = cls_conf[mask]

    cx, cy, w, h = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
    x1 = cx - w / 2
    y1 = cy - h / 2
    x2 = cx + w / 2
    y2 = cy + h / 2
    # letterbox 逆変換 → 元画像座標
    x1 = (x1 - dx) / r
    y1 = (y1 - dy) / r
    x2 = (x2 - dx) / r
    y2 = (y2 - dy) / r
    boxes = np.stack([x1, y1, x2, y2], axis=1)

    keep = _nms(boxes, cls_conf, _IOU_TH)
    out: List[Detection] = []
    for i in keep:
        bx1 = max(0.0, float(boxes[i, 0])) / orig_w
        by1 = max(0.0, float(boxes[i, 1])) / orig_h
        bx2 = min(float(orig_w), float(boxes[i, 2])) / orig_w
        by2 = min(float(orig_h), float(boxes[i, 3])) / orig_h
        if bx2 <= bx1 or by2 <= by1:
            continue
        out.append(Detection(bx1, by1, bx2, by2, float(cls_conf[i])))
    return out
