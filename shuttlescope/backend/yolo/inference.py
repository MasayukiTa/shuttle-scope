"""YOLO プレイヤー検出推論ラッパー

バックエンド優先順:
  1. OpenVINO IR (MULTI:GPU,CPU) — yolo/weights/yolov8n_openvino/yolov8n.xml
  2. ultralytics YOLOv8n  — pip install ultralytics で自動ダウンロード
  3. onnxruntime + カスタム ONNX  — backend/yolo/weights/yolo_badminton.onnx

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
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

WEIGHTS_DIR = Path(__file__).parent / "weights"
ONNX_MODEL = WEIGHTS_DIR / "yolo_badminton.onnx"
PT_MODEL = WEIGHTS_DIR / "yolo_badminton.pt"
OV_MODEL_DIR = WEIGHTS_DIR / "yolov8n_openvino"  # OpenVINO IR ディレクトリ

# コート座標分割しきい値（正規化 0-1）
COURT_MID_X = 0.5
DEPTH_FRONT_Y = 0.35   # これより小さい y = front（ネット側）
DEPTH_BACK_Y = 0.65    # これより大きい y = back（ベースライン側）

# 検出信頼度しきい値（バドミントン全景では選手が小さいため低めに設定）
MIN_CONF = 0.15


class YOLOInference:
    """YOLO プレイヤー検出ラッパー"""

    def __init__(self) -> None:
        self._loaded = False
        self._model = None
        self._backend: str = "unloaded"
        # 診断用: ロード失敗時のエラーメッセージ
        self._load_error: Optional[str] = None
        # 直前の推論診断情報（APIレスポンスに埋め込んで UI に表示する）
        self._last_debug: dict = {}
        # OpenVINO はステートフルなため同時呼び出し不可 → バッチスレッドとHTTPスレッドの競合を防ぐ
        self._lock = threading.Lock()

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

    def get_status_detail(self) -> dict:
        """診断用ステータスを返す。

        status_code:
          "ready"          — ロード済み、推論可能
          "weights_missing"— ultralytics あり、カスタム重みなし（auto-download で動作）
          "package_missing" — ultralytics も ONNX も存在しない
          "load_failed"    — ロード試行したが失敗
        """
        if self._loaded:
            return {
                "status_code": "ready",
                "backend": self._backend,
                "message": None,
            }

        # ultralytics パッケージ確認
        ultralytics_ok = False
        try:
            import ultralytics  # noqa: F401
            ultralytics_ok = True
        except ImportError:
            pass

        has_local_weights = ONNX_MODEL.exists() or PT_MODEL.exists()

        if self._load_error:
            return {
                "status_code": "load_failed",
                "backend": None,
                "message": self._load_error,
            }

        if not ultralytics_ok and not has_local_weights:
            return {
                "status_code": "package_missing",
                "backend": None,
                "message": "pip install ultralytics を実行してモデルを導入してください",
            }

        if ultralytics_ok and not has_local_weights:
            return {
                "status_code": "weights_missing",
                "backend": "ultralytics (auto-download)",
                "message": "初回バッチ実行時に yolov8n.pt が自動ダウンロードされます",
            }

        return {
            "status_code": "weights_missing",
            "backend": None,
            "message": "ONNX 重みが見つかりません: " + str(ONNX_MODEL),
        }

    # ─── モデルロード ────────────────────────────────────────────────────

    def load(self) -> bool:
        if self._loaded:
            return True

        # 1. OpenVINO 直接API (MULTI:GPU,CPU) — 最優先・最高速
        ov_xml = OV_MODEL_DIR / "yolov8n.xml"
        if ov_xml.exists():
            try:
                import openvino as ov
                core = ov.Core()
                available = core.available_devices
                # GPU優先（CPUアノテーション作業への影響を避けるため）
                device = "GPU" if "GPU" in available else "CPU"
                ov_model = core.read_model(str(ov_xml))
                compiled = core.compile_model(ov_model, device,
                                              {"PERFORMANCE_HINT": "LATENCY"})
                self._model = compiled
                self._ov_device = device
                self._backend = f"openvino:{device}"
                self._loaded = True
                self._load_error = None
                logger.info("YOLO loaded via OpenVINO direct API (device=%s)", device)
                return True
            except ImportError:
                logger.info("openvino not installed for YOLO, falling back")
            except Exception as exc:
                logger.warning("YOLO OpenVINO load failed: %s", exc)
                self._load_error = f"OpenVINO load failed: {exc}"

        # 2. ultralytics PT（yolov8n.pt を自動ダウンロード）
        try:
            from ultralytics import YOLO
            model_path = str(PT_MODEL) if PT_MODEL.exists() else "yolov8n.pt"
            self._model = YOLO(model_path)
            self._ov_device = None
            self._backend = "ultralytics"
            self._loaded = True
            self._load_error = None
            logger.info("YOLO loaded via ultralytics PT (path=%s)", model_path)
            return True
        except ImportError:
            logger.info("ultralytics not installed — trying onnxruntime fallback")
        except Exception as exc:
            logger.warning("ultralytics load failed: %s", exc)
            self._load_error = f"ultralytics load failed: {exc}"

        # 3. onnxruntime + カスタム ONNX
        if ONNX_MODEL.exists():
            try:
                import onnxruntime as ort
                self._model = ort.InferenceSession(
                    str(ONNX_MODEL), providers=["CPUExecutionProvider"]
                )
                self._ov_device = None
                self._backend = "onnx_cpu"
                self._loaded = True
                self._load_error = None
                logger.info("YOLO loaded via ONNX Runtime CPU")
                return True
            except Exception as exc:
                logger.warning("YOLO ONNX load failed: %s", exc)
                self._load_error = f"ONNX load failed: {exc}"

        logger.error(
            "YOLO: 使えるバックエンドがありません。"
            "pip install ultralytics を実行してください。"
        )
        return False

    # ─── 推論 ────────────────────────────────────────────────────────────

    def get_last_debug(self) -> dict:
        """直前の推論診断情報を返す（APIレスポンスに埋め込んで UI に表示する）"""
        return dict(self._last_debug)

    def predict_frame(self, frame) -> list[dict]:
        """1 フレームからプレイヤーを検出。失敗時は空リストを返す。

        スレッドセーフ: バッチスレッドとHTTPスレッドが同時に呼び出しても安全。
        OpenVINO は同期推論エンジンを共有するため _lock で排他制御する。
        """
        import numpy as _np
        if not self._loaded and not self.load():
            self._last_debug = {"error": "モデルロード失敗"}
            return []

        with self._lock:
            # フレーム基本情報
            h, w = frame.shape[:2]
            frame_mean = float(_np.mean(frame))
            self._last_debug = {
                "backend": self._backend,
                "frame_shape": [h, w],
                "frame_mean_brightness": round(frame_mean, 1),
                "threshold": MIN_CONF,
            }

            if frame_mean < 3.0:
                self._last_debug["warning"] = "フレームがほぼ黒（動画シーク失敗の可能性）"
                logger.warning("YOLO: frame is nearly black (mean=%.1f), seek may have failed", frame_mean)

            try:
                if self._backend.startswith("openvino:"):
                    detections = self._predict_openvino(frame)
                elif self._backend == "ultralytics":
                    detections = self._predict_ultralytics(frame)
                elif self._backend == "onnx_cpu":
                    detections = self._predict_onnx(frame)
                else:
                    self._last_debug["error"] = f"不明なバックエンド: {self._backend}"
                    return []
                result = self._assign_player_labels(detections)
                self._last_debug["detected"] = len(result)
                return result
            except Exception as exc:
                logger.exception("YOLO inference error (backend=%s): %s", self._backend, exc)
                self._last_debug["error"] = str(exc)
                return []

    def _predict_openvino(self, frame) -> list[dict]:
        """OpenVINO 直接API で YOLOv8n 推論（COCO person クラスのみ抽出）"""
        import cv2
        import numpy as np

        h, w = frame.shape[:2]
        img = cv2.resize(frame, (640, 640))
        img = img[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        inp = img[np.newaxis]

        # 推論: output shape は [1, 84, 8400] または [1, 8400, 84] の両方あり得る
        # 84 = 4(box) + 80(classes), 8400 = anchors
        result = self._model([inp])[self._model.output(0)]

        logger.info("YOLO OpenVINO raw result shape: %s dtype=%s", result.shape, result.dtype)

        # バッチ次元を除去して [84, 8400] または [8400, 84] に統一
        raw = result
        while raw.ndim > 2:
            raw = raw[0]  # [1, 84, 8400] → [84, 8400]

        logger.info("YOLO OpenVINO after squeeze shape: %s", raw.shape)

        # shape が (8400, 84) の場合は転置して (84, 8400) に統一
        if raw.ndim == 2 and raw.shape[0] != 84 and raw.shape[1] == 84:
            raw = raw.T  # → (84, 8400)
        elif raw.ndim == 2 and raw.shape[0] == 8400:
            raw = raw.T  # → (84, 8400)

        logger.info("YOLO OpenVINO normalized shape: %s", raw.shape)

        if raw.ndim != 2 or raw.shape[0] < 5:
            logger.warning("YOLO OpenVINO: unexpected output shape %s — skipping", raw.shape)
            return []

        import numpy as _np
        detections: list[dict] = []
        # person クラス = COCO index 0 → row index 4 (4 box coords の次)
        person_scores = raw[4]  # (8400,)
        cx, cy, bw, bh = raw[0], raw[1], raw[2], raw[3]

        top5 = sorted(person_scores.tolist(), reverse=True)[:5]
        above = int(_np.sum(person_scores >= MIN_CONF))
        logger.info(
            "YOLO OpenVINO person_scores: max=%.3f top5=%s anchors_above_threshold=%d (thresh=%.2f)",
            float(person_scores.max()),
            [round(v, 3) for v in top5],
            above,
            MIN_CONF,
        )
        self._last_debug.update({
            "output_shape": list(raw.shape),
            "person_score_max": round(float(person_scores.max()), 3),
            "person_score_top5": [round(v, 3) for v in top5],
            "anchors_above_threshold": above,
        })

        # NMS 省略版: 信頼度でフィルタ後、重複をシンプルな IoU で削除
        candidates = []
        for i in np.where(person_scores >= MIN_CONF)[0]:
            conf = float(person_scores[i])
            x1_n = max(0.0, float((cx[i] - bw[i] / 2) / 640))
            y1_n = max(0.0, float((cy[i] - bh[i] / 2) / 640))
            x2_n = min(1.0, float((cx[i] + bw[i] / 2) / 640))
            y2_n = min(1.0, float((cy[i] + bh[i] / 2) / 640))
            if x2_n > x1_n and y2_n > y1_n:
                candidates.append((conf, x1_n, y1_n, x2_n, y2_n))

        # 信頼度降順でグリーディ NMS
        candidates.sort(key=lambda c: c[0], reverse=True)
        kept: list[tuple] = []
        for cand in candidates:
            conf, x1, y1, x2, y2 = cand
            overlap = False
            for kc, kx1, ky1, kx2, ky2 in kept:
                ix1, iy1 = max(x1, kx1), max(y1, ky1)
                ix2, iy2 = min(x2, kx2), min(y2, ky2)
                if ix2 > ix1 and iy2 > iy1:
                    inter = (ix2 - ix1) * (iy2 - iy1)
                    a1 = (x2 - x1) * (y2 - y1)
                    a2 = (kx2 - kx1) * (ky2 - ky1)
                    iou = inter / (a1 + a2 - inter + 1e-6)
                    if iou > 0.45:
                        overlap = True
                        break
            if not overlap:
                kept.append(cand)

        for conf, x1_n, y1_n, x2_n, y2_n in kept:
            cx_n = (x1_n + x2_n) / 2
            cy_n = (y1_n + y2_n) / 2
            detections.append(self._make_entry(
                "person", conf,
                [x1_n, y1_n, x2_n, y2_n],
                cx_n, cy_n, cx_n, y2_n,
            ))

        return detections

    def _predict_ultralytics(self, frame) -> list[dict]:
        """ultralytics YOLOv8 で person クラスのみ検出"""
        results = self._model(frame, verbose=False, classes=[0])  # 0 = person
        if not results:
            return []

        result = results[0]
        h, w = frame.shape[:2]
        detections: list[dict] = []

        all_confs = [float(box.conf[0]) for box in result.boxes]
        top5 = sorted(all_confs, reverse=True)[:5]
        above = sum(1 for c in all_confs if c >= MIN_CONF)
        logger.info(
            "YOLO ultralytics: total_boxes=%d top5_conf=%s above_threshold=%d (thresh=%.2f)",
            len(all_confs), top5, above, MIN_CONF,
        )
        self._last_debug.update({
            "total_raw_boxes": len(all_confs),
            "person_score_top5": [round(v, 3) for v in top5],
            "person_score_max": round(top5[0], 3) if top5 else 0.0,
            "anchors_above_threshold": above,
        })

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
