"""YOLO プレイヤー検出推論ラッパー

バックエンド優先順:
  1. OpenVINO IR (MULTI:GPU,CPU) — yolo/weights/yolov8n_openvino/yolov8n.xml
  2. ultralytics YOLOv8n  — pip install ultralytics で自動ダウンロード
  3. onnxruntime + カスタム ONNX  — backend/yolo/weights/yolo_badminton.onnx

出力フォーマット（predict_frame）:
  [
    {
      "label": "player_a" | "player_b" | "player_c" | "player_d" | "player_other",
      "confidence": float,
      "bbox": [x1_n, y1_n, x2_n, y2_n],  # 正規化座標 0-1
      "centroid": [cx_n, cy_n],
      "foot_point": [fx_n, fy_n],          # bbox 下辺中央（足元推定）
      "court_side": "left" | "right",
      "depth_band": "front" | "mid" | "back",
      "track_id": int | (なし),            # ByteTrack 有効時のみ付与
    },
    ...
  ]

ラベル付け戦略（_assign_player_labels）:
  - ultralytics は COCO class 0 (person) のみ使用
  - 信頼度降順で上位 4 名を選手候補として選択
  - y 座標の中央値でコート奥側(player_a/b)・手前側(player_c/d)に分類
  - 同一ハーフ内は x 昇順（左 → 右）で a/b または c/d を割り当て
  - 5 人以上の余剰は player_other（観客・審判等）
  - ByteTrack 有効時（SS_YOLO_BYTETRACK=1）は track_id も付与
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


def _get_nms_iou_threshold() -> float:
    """person v2: NMS IoU しきい値を env から取得。
    デフォルト 0.45 (YOLO 標準)。SS_PERSON_NMS_IOU=0.30 にすると
    重なり気味の 2 人 (スマッシュ時 attacker/blocker など) を別 bbox として残しやすくなる。
    """
    import os as _os
    raw = _os.environ.get("SS_PERSON_NMS_IOU")
    if raw is None:
        return 0.45
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.45
    # 安全域: [0.05, 0.95]
    if v < 0.05 or v > 0.95:
        return 0.45
    return v


def _court_filter_enabled() -> bool:
    """person v2: court area filter の有効/無効。デフォルト ON。
    SS_PERSON_COURT_FILTER=0 で完全無効化。
    """
    import os as _os
    return _os.environ.get("SS_PERSON_COURT_FILTER", "1") != "0"


def _expand_polygon(polygon: list[list[float]], scale: float) -> list[list[float]]:
    """polygon の重心を中心に scale 倍に拡大する (margin 用)。
    凸 4 角形を想定 (コート 4 コーナー)。scale=1.0 で変化なし。
    """
    if not polygon:
        return polygon
    cx = sum(p[0] for p in polygon) / len(polygon)
    cy = sum(p[1] for p in polygon) / len(polygon)
    return [[cx + (p[0] - cx) * scale, cy + (p[1] - cy) * scale] for p in polygon]


def _point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    """Ray casting で点 in 多角形判定 (court_calibration.is_inside_court と同じ)。
    inference 側で court_calibration を import すると循環するため局所複製。
    """
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


class YOLOInference:
    """YOLO プレイヤー検出ラッパー"""

    # ByteTrack 設定ファイルパス
    _BT_YAML = Path(__file__).parent / "bytetrack.yaml"

    def __init__(self, cuda_device_index: int = 0, openvino_device: str = "GPU") -> None:
        self._loaded = False
        self._model = None
        self._backend: str = "unloaded"
        self._cuda_device_index = cuda_device_index
        self._openvino_device = openvino_device
        self._ul_device: str = "cpu"
        self._load_error: Optional[str] = None
        self._last_debug: dict = {}
        self._lock = threading.Lock()
        # ByteTrack: Track A1 (2026-05-04) でデフォルト ON に変更。
        # SS_YOLO_BYTETRACK=0 を明示すれば従来動作に戻せる。
        # 理由: フレーム間 ID 一貫性 = ラベル swap 削減、IdentityGraph の前提整備。
        import os as _os
        self._bt_enabled: bool = _os.environ.get("SS_YOLO_BYTETRACK", "1") != "0"
        # Track A1: track_id → label の継続マップ。
        # ByteTrack 有効時に同一 track_id が次フレームでも同ラベルを引き継ぐ。
        self._prev_track_labels: dict[int, str] = {}
        # person v2 court area filter: 試合ごとに 4 コーナー多角形を set すると、
        # 各検出の foot_point が拡張多角形外なら drop する (審判/掲示板/観客対策)。
        # None の場合は filter 無効 (キャリブ未設定試合の fail-safe)。
        self._court_polygon: Optional[list[list[float]]] = None
        # margin: court bbox を中心スケール (1.5x など) で拡張。スマッシュ後にライン
        # ギリギリ外に出る選手を許容するため。env で上書き可能 (SS_PERSON_COURT_MARGIN)。
        import os as _os2
        try:
            self._court_margin: float = float(_os2.environ.get("SS_PERSON_COURT_MARGIN", "1.5"))
        except (TypeError, ValueError):
            self._court_margin = 1.5
        self._court_polygon_expanded: Optional[list[list[float]]] = None

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

        # 0. ONNX + TensorRT EP — Phase 3.5 で追加 (PersonTracker 高速化用)。
        #    既存 OpenVINO/PT chain より優先。env SS_YOLO_USE_TRT=0 で無効化。
        #    fallback chain: TRT → CUDA → CPU (CPU は事実上ここでは使わず後段に任せる)。
        import os as _os_trt
        use_trt = _os_trt.environ.get("SS_YOLO_USE_TRT", "1") != "0"
        if use_trt and ONNX_MODEL.exists():
            try:
                import onnxruntime as ort
                available = set(ort.get_available_providers())
                if "TensorrtExecutionProvider" in available:
                    # WASB inference と同じ cache 規約。yolo 専用 sub-dir に分ける。
                    trt_cache = WEIGHTS_DIR / "trt_cache"
                    trt_cache.mkdir(parents=True, exist_ok=True)
                    trt_opts = {
                        "device_id": self._cuda_device_index,
                        "trt_engine_cache_enable": True,
                        "trt_engine_cache_path": str(trt_cache),
                        # fp16 は env で有効化可能 (デフォルト OFF — engine build 時間短縮優先)。
                        # SS_YOLO_TRT_FP16=1 で fp16 enable。
                    }
                    if _os_trt.environ.get("SS_YOLO_TRT_FP16", "0") == "1":
                        trt_opts["trt_fp16_enable"] = True
                    providers = [
                        ("TensorrtExecutionProvider", trt_opts),
                        ("CUDAExecutionProvider", {"device_id": self._cuda_device_index}),
                        "CPUExecutionProvider",
                    ]
                    sess_opts = ort.SessionOptions()
                    sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                    self._model = ort.InferenceSession(
                        str(ONNX_MODEL), sess_opts, providers=providers
                    )
                    self._ov_device = None
                    self._backend = f"onnx_trt:{self._cuda_device_index}"
                    self._loaded = True
                    self._load_error = None
                    logger.info(
                        "YOLO loaded via ONNX Runtime TensorRT EP (cache=%s, fp16=%s)",
                        trt_cache, trt_opts.get("trt_fp16_enable", False),
                    )
                    return True
                else:
                    logger.info("YOLO: TensorrtExecutionProvider 不在、TRT スキップ")
            except Exception as exc:
                logger.warning("YOLO TRT load failed: %s", exc)
                self._load_error = f"TRT load failed: {exc}"

        # 1. OpenVINO 直接API — 設定デバイス優先
        ov_xml = OV_MODEL_DIR / "yolov8n.xml"
        if ov_xml.exists():
            try:
                import openvino as ov
                core = ov.Core()
                available = core.available_devices
                # 設定値 → GPU → CPU の順で試行
                device_candidates: list[str] = []
                if self._openvino_device and self._openvino_device in available:
                    device_candidates.append(self._openvino_device)
                for fb in ("GPU", "CPU"):
                    if fb in available and fb not in device_candidates:
                        device_candidates.append(fb)
                device = device_candidates[0] if device_candidates else "CPU"
                ov_model = core.read_model(str(ov_xml))
                compiled = core.compile_model(ov_model, device, {"PERFORMANCE_HINT": "LATENCY"})
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

        # 2. ultralytics PT（CUDA 優先 → CPU フォールバック）
        try:
            from ultralytics import YOLO
            import torch
            model_path = str(PT_MODEL) if PT_MODEL.exists() else "yolov8n.pt"
            self._model = YOLO(model_path)
            if torch.cuda.is_available():
                self._ul_device = f"cuda:{self._cuda_device_index}"
                self._backend = f"ultralytics:cuda:{self._cuda_device_index}"
            else:
                self._ul_device = "cpu"
                self._backend = "ultralytics:cpu"
            self._ov_device = None
            self._loaded = True
            self._load_error = None
            logger.info("YOLO loaded via ultralytics PT (device=%s)", self._ul_device)
            return True
        except ImportError:
            logger.info("ultralytics not installed — trying onnxruntime fallback")
        except Exception as exc:
            logger.warning("ultralytics load failed: %s", exc)
            self._load_error = f"ultralytics load failed: {exc}"

        # 3. onnxruntime — CUDA → DirectML → CPU の順で試行
        if ONNX_MODEL.exists():
            try:
                import onnxruntime as ort
                avail = ort.get_available_providers()
                if "CUDAExecutionProvider" in avail:
                    providers = [
                        ("CUDAExecutionProvider", {"device_id": self._cuda_device_index}),
                        "CPUExecutionProvider",
                    ]
                    ep_name = f"onnx_cuda:{self._cuda_device_index}"
                elif "DmlExecutionProvider" in avail:
                    providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
                    ep_name = "onnx_directml"
                else:
                    providers = ["CPUExecutionProvider"]
                    ep_name = "onnx_cpu"
                self._model = ort.InferenceSession(str(ONNX_MODEL), providers=providers)
                self._ov_device = None
                self._backend = ep_name
                self._loaded = True
                self._load_error = None
                logger.info("YOLO loaded via ONNX Runtime (%s)", ep_name)
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
                elif self._backend.startswith("ultralytics"):
                    detections = self._predict_ultralytics(frame)
                elif self._backend.startswith("onnx"):
                    detections = self._predict_onnx(frame)
                else:
                    self._last_debug["error"] = f"不明なバックエンド: {self._backend}"
                    return []
                result = self._assign_player_labels(detections)
                # person v2: predict_frame は cropped 座標を返すため、ここでは
                # ROI が無い (= 全画面) 場合に限り court filter を適用する。
                # ROI crop 経由の呼び出しは router 側で remap 後に
                # filter_detections_by_court() を呼ぶこと。
                # _court_polygon は full-frame 正規化座標前提なので、
                # crop 中は適用しない (router 経路で明示適用)。
                if self._court_polygon_expanded is not None:
                    result = self._apply_court_filter(result)
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
        # person v2: SS_PERSON_NMS_IOU で IoU しきい値を緩められる (重なった 2 人保持)。
        nms_iou = _get_nms_iou_threshold()
        self._last_debug["nms_iou_threshold"] = nms_iou
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
                    if iou > nms_iou:
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
        """ultralytics YOLOv8 で person クラスのみ検出。
        SS_YOLO_BYTETRACK=1 の場合は ByteTrack で時系列 track_id を付与する。
        """
        # person v2: SS_PERSON_NMS_IOU で IoU しきい値を緩められる (重なり 2 人を残す)
        nms_iou = _get_nms_iou_threshold()
        if self._bt_enabled and self._BT_YAML.exists():
            results = self._model.track(
                frame, verbose=False, classes=[0], device=self._ul_device,
                persist=True, tracker=str(self._BT_YAML), iou=nms_iou,
            )
        else:
            results = self._model(
                frame, verbose=False, classes=[0], device=self._ul_device, iou=nms_iou,
            )
        if not results:
            return []

        result = results[0]
        h, w = frame.shape[:2]
        detections: list[dict] = []

        all_confs = [float(box.conf[0]) for box in result.boxes]
        top5 = sorted(all_confs, reverse=True)[:5]
        above = sum(1 for c in all_confs if c >= MIN_CONF)
        logger.info(
            "YOLO ultralytics: total_boxes=%d top5_conf=%s above_threshold=%d (thresh=%.2f) bytetrack=%s",
            len(all_confs), top5, above, MIN_CONF, self._bt_enabled,
        )
        self._last_debug.update({
            "total_raw_boxes": len(all_confs),
            "person_score_top5": [round(v, 3) for v in top5],
            "person_score_max": round(top5[0], 3) if top5 else 0.0,
            "anchors_above_threshold": above,
            "bytetrack_enabled": self._bt_enabled,
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
            fy_n = y2_n
            entry = self._make_entry(
                "person", conf,
                [x1_n, y1_n, x2_n, y2_n],
                cx_n, cy_n, cx_n, fy_n,
            )
            # ByteTrack が有効なら track_id を付与（_track_identities での強一致に利用）
            if self._bt_enabled and box.id is not None:
                entry["track_id"] = int(box.id[0])
            detections.append(entry)

        return detections

    def reset_tracker(self) -> None:
        """ByteTrack の状態をリセットする（バッチ処理開始時に呼び出す）。"""
        # Track A1: track_id 継続マップも合わせてクリア
        self.reset_label_continuity()
        if not self._bt_enabled:
            return
        try:
            if self._model is not None and hasattr(self._model, "predictor") and self._model.predictor is not None:
                self._model.predictor = None
                logger.info("YOLO ByteTrack: tracker reset")
        except Exception as exc:
            logger.warning("YOLO ByteTrack reset failed: %s", exc)

    def _predict_onnx(self, frame) -> list[dict]:
        """カスタム ONNX（YOLOv5/v8 形式）で検出。

        YOLOv8 ONNX export の出力 shape は次のどちらか:
          - [1, 4+C, 8400]  (C = クラス数。例: COCO 80 → 84、1-class fine-tuned → 5)
          - [1, N, 4+C+1]   (YOLOv5 形式、最後の +1 は obj_conf)

        ここでは shape を見て自動判別する。1-class モデル (yolov8n_v2_finetuned)
        と従来の COCO/3-class カスタムモデルの両方に対応。
        """
        import cv2
        import numpy as np

        h, w = frame.shape[:2]
        img = cv2.resize(frame, (640, 640))
        img = img[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        img = np.expand_dims(img, 0)

        input_name = self._model.get_inputs()[0].name
        raw = self._model.run(None, {input_name: img})[0]
        # raw shape を [N, ch] に正規化
        arr = raw
        while arr.ndim > 2:
            arr = arr[0]
        # YOLOv8 export は (4+C, 8400) → 転置して (8400, 4+C) に。
        # 8400 が大きい side。
        if arr.ndim == 2 and arr.shape[0] < arr.shape[1] and arr.shape[0] <= 128:
            arr = arr.T

        if arr.ndim != 2 or arr.shape[1] < 5:
            logger.warning("YOLO ONNX: unexpected output shape %s", arr.shape)
            return []

        cls_map = {0: "player_a", 1: "player_b", 2: "shuttle"}
        n_ch = arr.shape[1]
        # 判別:
        #   - v8 1-class:   ch=5   (cx,cy,w,h,conf)         → cls=0 固定、person
        #   - v8 multi-cls: ch=4+C (cx,cy,w,h,c0,c1,...)    → class score max
        #   - v5 形式:      ch=5+C (cx,cy,w,h,obj_conf,c..)
        detections: list[dict] = []
        for row in arr:
            cx640, cy640, bw640, bh640 = row[:4]
            if n_ch == 5:
                conf = float(row[4])
                cls_idx = 0
                label = "person"  # 1-class fine-tuned → 全部 person
            elif n_ch == 5 + 3 or (n_ch >= 6 and n_ch <= 8):
                # v5 形式: obj_conf * max(class_score)
                obj_conf = float(row[4])
                class_scores = row[5:]
                cls_idx = int(np.argmax(class_scores))
                conf = obj_conf * float(class_scores[cls_idx])
                label = cls_map.get(cls_idx, "person")
            else:
                # v8 multi-class: 4 + C
                class_scores = row[4:]
                cls_idx = int(np.argmax(class_scores))
                conf = float(class_scores[cls_idx])
                label = cls_map.get(cls_idx, "person")

            if conf < MIN_CONF:
                continue

            x1_n = max(0.0, float((cx640 - bw640 / 2) / 640))
            y1_n = max(0.0, float((cy640 - bh640 / 2) / 640))
            x2_n = min(1.0, float((cx640 + bw640 / 2) / 640))
            y2_n = min(1.0, float((cy640 + bh640 / 2) / 640))
            if x2_n <= x1_n or y2_n <= y1_n:
                continue
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

    # ダブルス対応: 最大 4 選手まで名前付きラベルを割り当て
    _PLAYER_LABELS = ["player_a", "player_b", "player_c", "player_d"]

    def _assign_player_labels(self, detections: list[dict]) -> list[dict]:
        """ultralytics の 'person' ラベルを player_a〜player_d に割り当て。

        Track A1 (2026-05-04): ByteTrack track_id 継続を最優先。
          1. 各 person 検出に track_id があり、前フレームで同じ track_id にラベルが
             割り当てられていれば、そのラベルをそのまま継続する。
          2. ラベル未確定の検出と未使用ラベルだけを、従来の位置ベースで割り当てる。
        これによりフレーム間のラベル swap が激減する。

        ダブルス（最大 4 名）対応:
        - 1〜4 人: 信頼度降順に上位 4 名を選択し、y 座標（奥→手前）→ x 座標の順でソート。
                   奥コート側（y 小）の 2 名が player_a/b、手前側（y 大）が player_c/d。
                   同じハーフ内は x 昇順（左→右）で a/b, c/d を割り当て。
        - 5 人以上: 低信頼の余剰分は player_other。
        既にカスタムラベル（player_a 等）がついている場合はそのまま。
        """
        persons = [d for d in detections if d["label"] == "person"]
        others  = [d for d in detections if d["label"] != "person"]

        # 信頼度降順で最大 4 名を「選手候補」として選ぶ
        persons_sorted_conf = sorted(persons, key=lambda d: d.get("confidence", 0.0), reverse=True)
        named = persons_sorted_conf[:4]
        extra = persons_sorted_conf[4:]

        # ── Track A1: 前フレームの track_id → label を再適用 ──
        # ByteTrack 有効時のみ意味を持つ (track_id が無い検出は skip)
        used_labels: set[str] = set()
        unresolved: list[dict] = []
        for p in named:
            tid = p.get("track_id")
            prev_label = self._prev_track_labels.get(tid) if tid is not None else None
            if (prev_label
                    and prev_label in self._PLAYER_LABELS
                    and prev_label not in used_labels):
                p["label"] = prev_label
                used_labels.add(prev_label)
            else:
                unresolved.append(p)

        # ── 残りを従来の位置ベース割当で埋める (未使用ラベルだけ使う) ──
        if unresolved:
            ys = [d["centroid"][1] for d in unresolved]
            y_mid = sum(ys) / len(ys)
            far  = sorted([d for d in unresolved if d["centroid"][1] <= y_mid], key=lambda d: d["centroid"][0])
            near = sorted([d for d in unresolved if d["centroid"][1]  > y_mid], key=lambda d: d["centroid"][0])
            ordered_unresolved = far + near
            free_labels = [lbl for lbl in self._PLAYER_LABELS if lbl not in used_labels]
            for p, lbl in zip(ordered_unresolved, free_labels):
                p["label"] = lbl
                used_labels.add(lbl)
            # それでも余ったら player_other
            for p in ordered_unresolved[len(free_labels):]:
                p["label"] = "player_other"

        for p in extra:
            p["label"] = "player_other"

        # ── prev_track_labels 更新 (今フレームの確定マップを保存) ──
        new_prev: dict[int, str] = {}
        for p in named:
            tid = p.get("track_id")
            lbl = p.get("label")
            if tid is not None and lbl in self._PLAYER_LABELS:
                new_prev[tid] = lbl
        self._prev_track_labels = new_prev

        return named + extra + others

    def reset_label_continuity(self) -> None:
        """ByteTrack reset と組で呼ぶ: track_id 継続マップをクリア。"""
        self._prev_track_labels = {}

    # ─── person v2 court area filter ────────────────────────────────────
    def set_court_polygon(
        self,
        polygon: Optional[list[list[float]]],
        margin: Optional[float] = None,
    ) -> None:
        """コート 4 コーナーの正規化座標多角形を設定。
        margin: 重心を中心としたスケール倍率 (>=1.0)。None なら env / デフォルト維持。
        polygon=None で filter を無効化する。
        """
        if polygon is None or len(polygon) < 3:
            self._court_polygon = None
            self._court_polygon_expanded = None
            return
        self._court_polygon = [list(p) for p in polygon]
        if margin is not None and margin >= 1.0:
            self._court_margin = float(margin)
        self._court_polygon_expanded = _expand_polygon(
            self._court_polygon, max(1.0, self._court_margin)
        )

    def clear_court_polygon(self) -> None:
        """court area filter を解除 (バッチ終了時など)。"""
        self._court_polygon = None
        self._court_polygon_expanded = None

    def _apply_court_filter(self, detections: list[dict]) -> list[dict]:
        """foot_point (足元) が拡張コート多角形の外なら drop。
        polygon 未設定 / env で無効化 / 多角形不正 のときは何もしない (fail-safe)。
        """
        if not _court_filter_enabled():
            return detections
        poly = self._court_polygon_expanded
        if not poly or len(poly) < 3:
            return detections
        kept: list[dict] = []
        dropped = 0
        for d in detections:
            # person 系のみフィルタ対象 (shuttle 等は素通し)
            label = d.get("label", "")
            if not (label.startswith("player_") or label == "person" or label == "player_other"):
                kept.append(d)
                continue
            fp = d.get("foot_point") or d.get("centroid")
            if not fp or len(fp) < 2:
                kept.append(d)
                continue
            if _point_in_polygon(float(fp[0]), float(fp[1]), poly):
                kept.append(d)
            else:
                dropped += 1
        if dropped:
            self._last_debug["court_filter_dropped"] = dropped
        return kept


# ─── 公開ヘルパー: full-frame 座標で court area filter ────────────────────

def filter_detections_by_court(
    detections: list[dict],
    polygon: Optional[list[list[float]]],
    margin: float = 1.5,
) -> list[dict]:
    """ROI remap 後の (= 動画全体正規化座標) detections に court filter を適用。
    polygon=None / [] / 不正なら何もしない (fail-safe)。
    env SS_PERSON_COURT_FILTER=0 でも完全 no-op。
    """
    if not _court_filter_enabled():
        return detections
    if not polygon or len(polygon) < 3:
        return detections
    expanded = _expand_polygon([list(p) for p in polygon], max(1.0, margin))
    kept: list[dict] = []
    for d in detections:
        label = d.get("label", "")
        if not (label.startswith("player_") or label == "person" or label == "player_other"):
            kept.append(d)
            continue
        fp = d.get("foot_point") or d.get("centroid")
        if not fp or len(fp) < 2:
            kept.append(d)
            continue
        if _point_in_polygon(float(fp[0]), float(fp[1]), expanded):
            kept.append(d)
    return kept


# ─── シングルトン ────────────────────────────────────────────────────────

_instance: Optional[YOLOInference] = None


def get_yolo_inference(cuda_device_index: int = 0,
                       openvino_device: str = "GPU") -> YOLOInference:
    global _instance
    config_changed = (
        _instance is None
        or _instance._cuda_device_index != cuda_device_index
        or _instance._openvino_device != openvino_device
    )
    if config_changed:
        _instance = YOLOInference(
            cuda_device_index=cuda_device_index,
            openvino_device=openvino_device,
        )
    return _instance
