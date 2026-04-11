"""TrackNet inference wrapper.

Runtime priority:
1. OpenVINO
2. ONNX Runtime CPU
3. TensorFlow CPU / Intel

The currently bundled real pretrained weights are the public badminton-specific
TensorFlow checkpoint. ONNX / OpenVINO remain optional acceleration targets.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

INPUT_W, INPUT_H = 512, 288
FRAME_STACK = 3

WEIGHTS_DIR = Path(__file__).parent / "weights"
TF_CKPT_PREFIX = WEIGHTS_DIR / "TrackNet"

ONNX_CANDIDATES = [
    WEIGHTS_DIR / "tracknet.onnx",
    WEIGHTS_DIR / "tracknet_v2.onnx",
]
OPENVINO_XML_CANDIDATES = [
    WEIGHTS_DIR / "tracknet.xml",
    WEIGHTS_DIR / "tracknet_v2.xml",
]


def _existing_path(paths: list[Path]) -> Optional[Path]:
    for path in paths:
        if path.exists():
            return path
    return None


class TrackNetInference:
    def __init__(self, backend: str = "auto", device: str = "GPU"):
        self._infer_fn = None
        self._backend_name = "unloaded"
        self._device = device
        self._backend = backend
        self._load_error: Optional[str] = None

    def get_load_error(self) -> Optional[str]:
        """ロード失敗時の具体的な理由を返す。成功時または未試行時は None。"""
        return self._load_error

    def is_available(self) -> bool:
        tf_ckpt_exists = (TF_CKPT_PREFIX.with_suffix(".index").exists() and
                          TF_CKPT_PREFIX.parent.joinpath("TrackNet.data-00000-of-00001").exists())
        return (
            tf_ckpt_exists
            or _existing_path(ONNX_CANDIDATES) is not None
            or _existing_path(OPENVINO_XML_CANDIDATES) is not None
        )

    def load(self) -> bool:
        if self._infer_fn is not None:
            return True

        if not self.is_available():
            logger.warning("TrackNet weights not found at %s", WEIGHTS_DIR)
            self._load_error = "重みファイルが見つかりません"
            return False

        tried: list[str] = []
        # 指定バックエンドのファイルが存在しない場合は auto にフォールバックして他を試みる
        effective_backend = self._backend

        openvino_xml = _existing_path(OPENVINO_XML_CANDIDATES)
        if effective_backend in ("auto", "openvino"):
            if openvino_xml is None:
                if effective_backend == "openvino":
                    tried.append("openvino: XMLファイルが見つかりません（自動フォールバック）")
                    logger.info("openvino backend requested but no XML found, falling back to auto")
                    effective_backend = "auto"
            else:
                try:
                    import openvino as ov

                    core = ov.Core()
                    available = core.available_devices

                    # GPU優先（CPUアノテーション作業への影響を避けるため）
                    # GPU不在の場合のみ CPU にフォールバック
                    device_candidates = []
                    if "GPU" in available:
                        device_candidates.append("GPU")
                    device_candidates.append("CPU")

                    ov_model = core.read_model(str(openvino_xml))

                    for dev in device_candidates:
                        try:
                            config = {"PERFORMANCE_HINT": "THROUGHPUT"}
                            compiled = core.compile_model(ov_model, dev, config)
                            input_name = compiled.input(0).any_name
                            req = compiled.create_infer_request()
                            self._infer_fn = lambda frames, _req=req, _name=input_name: \
                                self._run_openvino(_req, _name, frames)
                            self._backend_name = f"openvino:{dev}"
                            self._load_error = None
                            logger.info("TrackNet loaded via OpenVINO on %s", dev)
                            return True
                        except Exception as exc:
                            tried.append(f"openvino:{dev}: {exc}")
                            continue
                except ImportError:
                    logger.info("openvino not installed, falling back")
                    tried.append("openvino: パッケージ未インストール")
                    effective_backend = "auto"

        onnx_model = _existing_path(ONNX_CANDIDATES)
        if effective_backend in ("auto", "onnx_cpu"):
            if onnx_model is None:
                tried.append("onnx_cpu: ONNXファイルが見つかりません")
            else:
                try:
                    import onnxruntime as ort

                    sess = ort.InferenceSession(str(onnx_model), providers=["CPUExecutionProvider"])
                    input_name = sess.get_inputs()[0].name
                    self._infer_fn = lambda frames: self._run_onnx(sess, input_name, frames)
                    self._backend_name = "onnx_cpu"
                    self._load_error = None
                    logger.info("TrackNet loaded via ONNX Runtime CPU")
                    return True
                except ImportError:
                    tried.append("onnxruntime: パッケージ未インストール")
                    logger.info("onnxruntime not installed, falling back")
                except Exception as exc:
                    tried.append(f"onnxruntime: {exc}")

        if effective_backend in ("auto", "tensorflow_cpu") and TF_CKPT_PREFIX.with_suffix(".index").exists():
            try:
                from backend.tracknet.model import build_tracknet_model

                model = build_tracknet_model()
                model.load_weights(str(TF_CKPT_PREFIX)).expect_partial()
                self._infer_fn = lambda frames: self._run_tensorflow(model, frames)
                self._backend_name = "tensorflow_cpu"
                self._load_error = None
                logger.info("TrackNet loaded via TensorFlow CPU/Intel backend")
                return True
            except ImportError:
                tried.append("tensorflow: パッケージ未インストール")
                logger.warning("tensorflow is not installed")
            except Exception as exc:
                tried.append(f"tensorflow: {exc}")
                logger.exception("TrackNet TensorFlow load failed: %s", exc)

        self._load_error = "使えるバックエンドがありません。試みたバックエンド: " + "; ".join(tried) if tried else "重みファイルが見つかりません"
        logger.error("TrackNet: no usable inference backend found. %s", self._load_error)
        return False

    def backend_name(self) -> str:
        return self._backend_name

    def predict_frames(self, frames: list[np.ndarray]) -> list[dict]:
        if self._infer_fn is None and not self.load():
            return []

        results = []
        for i in range(len(frames) - FRAME_STACK + 1):
            triplet = frames[i : i + FRAME_STACK]
            inp = self._preprocess(triplet)
            heatmap = self._infer_fn(inp)

            from backend.tracknet.zone_mapper import heatmap_to_zone

            zone, conf, coords = heatmap_to_zone(heatmap)
            results.append(
                {
                    "frame_idx": i + 1,
                    "zone": zone,
                    "confidence": round(conf, 3),
                    "x_norm": round(coords[0], 4) if coords else None,
                    "y_norm": round(coords[1], 4) if coords else None,
                }
            )

        return results

    def _preprocess(self, frames: list[np.ndarray]) -> np.ndarray:
        import cv2

        channels = []
        for frame in frames:
            resized = cv2.resize(frame, (INPUT_W, INPUT_H))
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
            channels.append(gray)
        stacked = np.stack(channels, axis=0)  # (3, H, W)
        return stacked[np.newaxis].astype(np.float32)  # (1, 3, H, W)

    def _run_openvino(self, req, input_name: str, inp: np.ndarray) -> np.ndarray:
        req.infer(inputs={input_name: inp})
        out = req.get_output_tensor(0).data
        return out[0, 0]

    def _run_onnx(self, sess, input_name: str, inp: np.ndarray) -> np.ndarray:
        out = sess.run(None, {input_name: inp})[0]
        return out[0, 0]

    def _run_tensorflow(self, model, inp: np.ndarray) -> np.ndarray:
        out = model(inp, training=False).numpy()
        return out[0, 0]


_instance: Optional[TrackNetInference] = None


def get_inference(backend: str = "auto") -> TrackNetInference:
    global _instance
    if _instance is None or (_instance._backend != backend and backend != "auto"):
        _instance = TrackNetInference(backend=backend)
    return _instance
