# ReID モデル配置ディレクトリ

## OSNet ONNX（任意・強化用）

このディレクトリに `osnet_x0_25.onnx` を置くと、選手再同定の特徴量抽出が
OSNet ベース（512-d 学習済み embedding）に切り替わります。

未配置時は HSV 3D hist + LBP (315-d, ヒューリスティック) にフォールバックします。
フォールバックでも従来の Hue-only 12-bin から大幅に精度向上します。

### OSNet ONNX の入手手順

1. BoxMOT リリースページから `osnet_x0_25_msmt17.onnx` を取得:
   <https://github.com/mikel-brostrom/yolo_tracking/releases>
   または torchreid (<https://kaiyangzhou.github.io/deep-person-reid/MODEL_ZOO>) から
   `osnet_x0_25_msmt17.pt` を取り、`torch.onnx.export` で 256×128 入力の ONNX に変換。

2. ファイル名を `osnet_x0_25.onnx` にリネームしてこのディレクトリに配置。

3. backend 再起動。ログに `ReID: OSNet ONNX loaded` が出れば OK。

### 仕様（ONNX 側）

- 入力: `[1, 3, 256, 128]` float32 (ImageNet mean/std 正規化, RGB)
- 出力: `[1, 512]` float32 embedding（未正規化で可、内部で L2 正規化する）
