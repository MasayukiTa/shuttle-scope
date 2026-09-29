"""YOLO live adapter — プレイヤー検出・サイド推定（スキャフォールド）

実際のモデルウェイトが配置されるまでは全メソッドが安全なフォールバックを返す。
インターフェースは TrackNet inference と統一している。

モデルウェイト配置場所:
    backend/yolo/weights/yolo_badminton.onnx  (推奨: YOLOv8 ONNX)
    backend/yolo/weights/yolo_badminton.pt    (PyTorch fallback)
"""
from backend.yolo.inference import YOLOInference, get_yolo_inference

__all__ = ["YOLOInference", "get_yolo_inference"]
