# TrackNet 系シャトル検出モジュール (現行の既定検出器)
# 実体: Chang-Chia-Chi/TrackNet-Badminton-Tracking-tensorflow2 の非公式実装 (チェックポイントを ONNX / OpenVINO / TensorRT へ変換)。
#   上流 README: 非公式 / ResNet + U-Net / 連続 3 フレームのグレースケール入力 / 512x288 / focal loss。
#   TrackNet V3 (8 フレーム + 背景画像 + 軌跡補正) の説明とは一致しない。V2 と一致するかは未確認。
#   ドキュメントの「TrackNetV3」「TrackNet V2」は、この実装を指す通称で、版の裏付けはない。
# アーキテクチャ: Chang-Chia-Chi/TrackNet (MIT License)
# 推論エンジン: OpenVINO (Apache 2.0) / ONNX Runtime (MIT)
