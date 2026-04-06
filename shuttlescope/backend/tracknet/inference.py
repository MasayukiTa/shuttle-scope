"""TrackNet V2 推論ラッパー
OpenVINO（推奨）または ONNX Runtime CPU（フォールバック）で動作。
"""
import os
import logging
from pathlib import Path
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

# 標準解像度（TrackNetV2 学習時）
INPUT_W, INPUT_H = 512, 288
# 3フレーム × 3チャネル = 9チャネル
INPUT_C = 9

WEIGHTS_DIR = Path(__file__).parent / "weights"
OPENVINO_XML = WEIGHTS_DIR / "tracknet_v2.xml"
OPENVINO_BIN = WEIGHTS_DIR / "tracknet_v2.bin"
ONNX_MODEL   = WEIGHTS_DIR / "tracknet_v2.onnx"


class TrackNetInference:
    """TrackNet V2 推論クラス。
    バックエンドは OpenVINO → ONNX CPU の優先順で自動選択。
    """

    def __init__(self, backend: str = "auto", device: str = "GPU"):
        """
        backend: 'openvino' | 'onnx_cpu' | 'auto'
        device:  OpenVINO デバイス名 ('GPU', 'CPU', 'AUTO')
        """
        self._infer_fn = None
        self._backend_name = "unloaded"
        self._device = device
        self._backend = backend

    def is_available(self) -> bool:
        """モデルウェイトが配置されているかどうかを返す"""
        return ONNX_MODEL.exists() or (OPENVINO_XML.exists() and OPENVINO_BIN.exists())

    def load(self) -> bool:
        """推論エンジンをロード。失敗しても例外を投げず False を返す。"""
        if self._infer_fn is not None:
            return True  # 既にロード済み

        if not self.is_available():
            logger.warning("TrackNet weights not found at %s", WEIGHTS_DIR)
            return False

        # OpenVINO を試みる
        if self._backend in ("auto", "openvino") and OPENVINO_XML.exists():
            try:
                from openvino.runtime import Core
                ie = Core()
                model = ie.read_model(str(OPENVINO_XML))
                # GPU（Iris Xe）→ CPU フォールバック
                for dev in [self._device, "CPU"]:
                    try:
                        compiled = ie.compile_model(model, dev)
                        req = compiled.create_infer_request()
                        self._infer_fn = lambda frames: self._run_openvino(req, frames)
                        self._backend_name = f"openvino:{dev}"
                        logger.info("TrackNet loaded via OpenVINO on %s", dev)
                        return True
                    except Exception:
                        continue
            except ImportError:
                logger.info("openvino not installed, falling back to ONNX")

        # ONNX Runtime CPU
        if self._backend in ("auto", "onnx_cpu") and ONNX_MODEL.exists():
            try:
                import onnxruntime as ort
                sess = ort.InferenceSession(
                    str(ONNX_MODEL),
                    providers=["CPUExecutionProvider"],
                )
                self._infer_fn = lambda frames: self._run_onnx(sess, frames)
                self._backend_name = "onnx_cpu"
                logger.info("TrackNet loaded via ONNX Runtime CPU")
                return True
            except ImportError:
                logger.warning("onnxruntime not installed")

        logger.error("TrackNet: no usable inference backend found")
        return False

    def backend_name(self) -> str:
        return self._backend_name

    def predict_frames(
        self,
        frames: list[np.ndarray],  # list of (H, W, 3) uint8 BGR
    ) -> list[dict]:
        """3フレームずつウィンドウを滑らせて推論。
        Returns: list of { frame_idx, x_norm, y_norm, confidence }
        """
        if self._infer_fn is None:
            if not self.load():
                return []

        results = []
        n = len(frames)

        for i in range(n - 2):
            triplet = frames[i : i + 3]
            inp = self._preprocess(triplet)   # (1, 9, H, W) float32
            heatmap = self._infer_fn(inp)     # (H, W) float32

            from backend.tracknet.zone_mapper import heatmap_to_zone
            zone, conf, coords = heatmap_to_zone(heatmap)

            results.append({
                "frame_idx": i + 1,  # 中央フレーム
                "zone": zone,
                "confidence": round(conf, 3),
                "x_norm": round(coords[0], 4) if coords else None,
                "y_norm": round(coords[1], 4) if coords else None,
            })

        return results

    # ───────────────────────────────────────────────────────
    # Private

    def _preprocess(self, frames: list[np.ndarray]) -> np.ndarray:
        """3フレームを正規化・リサイズして (1, 9, H, W) に変換"""
        import cv2
        channels = []
        for frame in frames:
            resized = cv2.resize(frame, (INPUT_W, INPUT_H))
            # BGR→RGB、0~1正規化
            rgb = resized[:, :, ::-1].astype(np.float32) / 255.0
            channels.append(rgb.transpose(2, 0, 1))  # (3, H, W)
        stacked = np.concatenate(channels, axis=0)    # (9, H, W)
        return stacked[np.newaxis]                    # (1, 9, H, W)

    def _run_openvino(self, req, inp: np.ndarray) -> np.ndarray:
        req.infer(inputs={"input": inp})
        out = req.get_output_tensor(0).data  # (1, 1, H, W)
        return out[0, 0]

    def _run_onnx(self, sess, inp: np.ndarray) -> np.ndarray:
        out = sess.run(None, {"input": inp})[0]  # (1, 1, H, W)
        return out[0, 0]


# シングルトン
_instance: Optional[TrackNetInference] = None


def get_inference(backend: str = "auto") -> TrackNetInference:
    global _instance
    if _instance is None:
        _instance = TrackNetInference(backend=backend)
    return _instance
