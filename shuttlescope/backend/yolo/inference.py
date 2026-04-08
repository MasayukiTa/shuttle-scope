"""YOLO プレイヤー検出推論ラッパー（スキャフォールド）

インターフェース:
    is_available() → bool          モデルファイルが存在するか
    load() → bool                  モデルをロードするか（失敗時 False）
    predict_frame(frame) → list    1 フレームから検出結果を返す

戻り値フォーマット（predict_frame）:
    [
        {
            "label": "player_a" | "player_b" | "shuttle",
            "confidence": float,
            "bbox": [x1, y1, x2, y2],   # 正規化座標 0-1
            "side": "left" | "right" | None,
        },
        ...
    ]

将来の実装想定:
    - YOLOv8 ONNX: backend/yolo/weights/yolo_badminton.onnx
    - onnxruntime で CPU 推論
    - OpenVINO で INT8 高速化

現時点ではモデル未導入のため全メソッドがスタブを返す。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

WEIGHTS_DIR = Path(__file__).parent / "weights"
ONNX_MODEL = WEIGHTS_DIR / "yolo_badminton.onnx"
PT_MODEL   = WEIGHTS_DIR / "yolo_badminton.pt"


class YOLOInference:
    """YOLO プレイヤー検出ラッパー（未実装スタブ）"""

    def __init__(self):
        self._loaded = False
        self._model = None

    def is_available(self) -> bool:
        """ウェイトファイルが存在すれば True"""
        return ONNX_MODEL.exists() or PT_MODEL.exists()

    def load(self) -> bool:
        """モデルをロードする。失敗時は False を返す。"""
        if self._loaded:
            return True
        if not self.is_available():
            logger.info("YOLO weights not found — inference unavailable")
            return False
        try:
            if ONNX_MODEL.exists():
                import onnxruntime as ort  # type: ignore
                self._model = ort.InferenceSession(str(ONNX_MODEL))
                self._loaded = True
                logger.info("YOLO ONNX model loaded: %s", ONNX_MODEL)
                return True
        except Exception as exc:
            logger.warning("YOLO model load failed: %s", exc)
        return False

    def predict_frame(self, frame) -> list[dict]:
        """1 フレームからプレイヤー検出を実行。モデル未導入時は空リストを返す。"""
        if not self._loaded:
            return []
        try:
            return self._run_inference(frame)
        except Exception as exc:
            logger.warning("YOLO inference error: %s", exc)
            return []

    def _run_inference(self, frame) -> list[dict]:
        """ONNX モデルで推論実行（ウェイト配置後に実装）"""
        # TODO: 実際の ONNX 推論コードをここに実装
        # 期待される実装:
        #   1. frame を 640x640 にリサイズ
        #   2. ONNX セッションで推論
        #   3. NMS で重複除去
        #   4. bbox を正規化座標に変換
        #   5. label を "player_a" / "player_b" / "shuttle" にマッピング
        return []

    def backend_name(self) -> Optional[str]:
        if not self._loaded:
            return None
        return "onnx_cpu"


# シングルトン
_instance: Optional[YOLOInference] = None


def get_yolo_inference() -> YOLOInference:
    global _instance
    if _instance is None:
        _instance = YOLOInference()
    return _instance
