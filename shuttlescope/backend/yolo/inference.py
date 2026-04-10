"""YOLO プレイヤー検出推論ラッパー

バックエンド優先順:
  1. ultralytics YOLOv8n  — pip install ultralytics で自動ダウンロード
  2. onnxruntime + カスタム ONNX  — backend/yolo/weights/yolo_badminton.onnx

出力フォーマット（predict_frame）:
  [
    {
      "label": "player_a" | "player_b" | "player_other",
      "confidence": float,
      "bbox": [x1_n, y1_n, x2_n, y2_n],  # 正規化座標 0-1
      "centroid": [cx_n, cy_n],
      "foot_point": [fx_n, fy_n],          # bbox 下辺中央（足元推定）
      "court_side": "left" | "right",
      "depth_band": "front" | "mid" | "back",
    },
    ...
  ]

ラベル付け戦略:
  - ultralytics は COCO class 0 (person) のみ使用
  - x 座標が小さい方を player_a、大きい方を player_b に割り当て
  - カスタム ONNX は cls=0/1/2 を player_a/player_b/shuttle として扱う
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

WEIGHTS_DIR = Path(__file__).parent / "weights"
ONNX_MODEL = WEIGHTS_DIR / "yolo_badminton.onnx"
PT_MODEL = WEIGHTS_DIR / "yolo_badminton.pt"

# コート座標分割しきい値（正規化 0-1）
COURT_MID_X = 0.5
DEPTH_FRONT_Y = 0.35   # これより小さい y = front（ネット側）
DEPTH_BACK_Y = 0.65    # これより大きい y = back（ベースライン側）

# 検出信頼度しきい値
MIN_CONF = 0.30


class YOLOInference:
    """YOLO プレイヤー検出ラッパー"""

    def __init__(self) -> None:
        self._loaded = False
        self._model = None
        self._backend: str = "unloaded"

    # ─── 可用性確認 ─────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """ultralytics が使えるか、またはローカル重みが存在すれば True"""
        try:
            import ultralytics  # noqa: F401
            return True
        except ImportError:
            pass
        return ONNX_MODEL.exists() or PT_MODEL.exists()

    def backend_name(self) -> Optional[str]:
        return self._backend if self._loaded else None

    # ─── モデルロード ────────────────────────────────────────────────────

    def load(self) -> bool:
        if self._loaded:
            return True

        # 1. ultralytics（yolov8n.pt を自動ダウンロード）
        try:
            from ultralytics import YOLO
            model_path = str(PT_MODEL) if PT_MODEL.exists() else "yolov8n.pt"
            self._model = YOLO(model_path)
            self._backend = "ultralytics"
            self._loaded = True
            logger.info("YOLO loaded via ultralytics (path=%s)", model_path)
            return True
        except ImportError:
            logger.info("ultralytics not installed — trying onnxruntime fallback")
        except Exception as exc:
            logger.warning("ultralytics load failed: %s", exc)

        # 2. onnxruntime + カスタム ONNX
        if ONNX_MODEL.exists():
            try:
                import onnxruntime as ort
                self._model = ort.InferenceSession(
                    str(ONNX_MODEL), providers=["CPUExecutionProvider"]
                )
                self._backend = "onnx_cpu"
                self._loaded = True
                logger.info("YOLO loaded via ONNX Runtime CPU")
                return True
            except Exception as exc:
                logger.warning("YOLO ONNX load failed: %s", exc)

        logger.error(
            "YOLO: 使えるバックエンドがありません。"
            "pip install ultralytics を実行してください。"
        )
        return False

    # ─── 推論 ────────────────────────────────────────────────────────────

    def predict_frame(self, frame) -> list[dict]:
        """1 フレームからプレイヤーを検出。失敗時は空リストを返す。"""
        if not self._loaded and not self.load():
            return []
        try:
            if self._backend == "ultralytics":
                detections = self._predict_ultralytics(frame)
            elif self._backend == "onnx_cpu":
                detections = self._predict_onnx(frame)
            else:
                return []
            return self._assign_player_labels(detections)
        except Exception as exc:
            logger.warning("YOLO inference error: %s", exc)
            return []

    def _predict_ultralytics(self, frame) -> list[dict]:
        """ultralytics YOLOv8 で person クラスのみ検出"""
        results = self._model(frame, verbose=False, classes=[0])  # 0 = person
        if not results:
            return []

        result = results[0]
        h, w = frame.shape[:2]
        detections: list[dict] = []

        for box in result.boxes:
            conf = float(box.conf[0])
            if conf < MIN_CONF:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            x1_n, y1_n = x1 / w, y1 / h
            x2_n, y2_n = x2 / w, y2 / h
            cx_n = (x1_n + x2_n) / 2
            cy_n = (y1_n + y2_n) / 2
            fy_n = y2_n  # foot_point = bbox 下辺中央
            detections.append(self._make_entry(
                "person", conf,
                [x1_n, y1_n, x2_n, y2_n],
                cx_n, cy_n, cx_n, fy_n,
            ))

        return detections

    def _predict_onnx(self, frame) -> list[dict]:
        """カスタム ONNX（YOLOv5/v8 形式）で検出"""
        import cv2
        import numpy as np

        h, w = frame.shape[:2]
        img = cv2.resize(frame, (640, 640))
        img = img[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        img = np.expand_dims(img, 0)

        input_name = self._model.get_inputs()[0].name
        raw = self._model.run(None, {input_name: img})[0]

        detections: list[dict] = []
        for row in raw[0]:
            if len(row) < 5:
                continue
            conf = float(row[4])
            if conf < MIN_CONF:
                continue
            cls_idx = int(row[5]) if len(row) > 5 else 0
            cls_map = {0: "player_a", 1: "player_b", 2: "shuttle"}
            label = cls_map.get(cls_idx, "person")

            cx640, cy640, bw640, bh640 = row[:4]
            x1_n = max(0.0, (cx640 - bw640 / 2) / 640)
            y1_n = max(0.0, (cy640 - bh640 / 2) / 640)
            x2_n = min(1.0, (cx640 + bw640 / 2) / 640)
            y2_n = min(1.0, (cy640 + bh640 / 2) / 640)
            cx_n = (x1_n + x2_n) / 2
            cy_n = (y1_n + y2_n) / 2
            detections.append(self._make_entry(
                label, conf,
                [x1_n, y1_n, x2_n, y2_n],
                cx_n, cy_n, cx_n, y2_n,
            ))

        return detections

    # ─── 内部ヘルパー ────────────────────────────────────────────────────

    def _make_entry(
        self,
        label: str,
        conf: float,
        bbox: list[float],
        cx_n: float,
        cy_n: float,
        fx_n: float,
        fy_n: float,
    ) -> dict:
        return {
            "label": label,
            "confidence": round(conf, 3),
            "bbox": [round(v, 4) for v in bbox],
            "centroid": [round(cx_n, 4), round(cy_n, 4)],
            "foot_point": [round(fx_n, 4), round(fy_n, 4)],
            "court_side": "left" if cx_n < COURT_MID_X else "right",
            "depth_band": (
                "front" if cy_n < DEPTH_FRONT_Y
                else "back" if cy_n > DEPTH_BACK_Y
                else "mid"
            ),
        }

    def _assign_player_labels(self, detections: list[dict]) -> list[dict]:
        """ultralytics の 'person' ラベルを player_a / player_b に割り当て。
        x 座標昇順: 左 = player_a、右 = player_b。
        3 人以上は player_other。
        既にカスタムラベル（player_a 等）がついている場合はそのまま。
        """
        persons = [d for d in detections if d["label"] == "person"]
        others = [d for d in detections if d["label"] != "person"]

        persons_sorted = sorted(persons, key=lambda d: d["centroid"][0])
        labels = ["player_a", "player_b"]
        for i, p in enumerate(persons_sorted):
            p["label"] = labels[i] if i < len(labels) else "player_other"

        return persons_sorted + others


# ─── シングルトン ────────────────────────────────────────────────────────

_instance: Optional[YOLOInference] = None


def get_yolo_inference() -> YOLOInference:
    global _instance
    if _instance is None:
        _instance = YOLOInference()
    return _instance
