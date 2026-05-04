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

---

## YOLOv8n ONNX（ブラウザ中継リアルタイム YOLO 用）

このディレクトリに `yolov8n.onnx` を置くと、ブラウザ中継（iOS→オペレーター PC）の
受信映像に対してオペレーター PC 側で軽量リアルタイム YOLO（~55fps+）が有効化されます。

未配置時は DeviceManagerPanel の「リアルタイム YOLO」トグルが無効化され、
バックエンド `/ws/yolo/realtime/*` が 503 相当で閉じます。重処理のバッチ YOLO
（既存 `backend/routers/yolo.py`）は本機能と独立に動作するため影響ありません。

### 入手手順

1. Ultralytics 公式の事前学習モデルを ONNX にエクスポート:
   ```bash
   pip install ultralytics
   python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx', imgsz=(384,640), opset=12, simplify=True)"
   ```
   これで `yolov8n.onnx` が生成されます。

2. ファイルをこのディレクトリに `yolov8n.onnx` として配置。

3. backend 再起動。ログに `YOLOv8n ONNX loaded` が出れば OK。

### 仕様（ONNX 側）

- 入力: `[1, 3, 384, 640]` float32 RGB（0-1 スケール、pad letterbox）
- 出力: `[1, 84, N]` 形式（ultralytics 既定）または `[1, N, 84]` いずれも許容
- 本実装では person (class 0) のみ抽出、conf>=0.35、IoU NMS 0.45

### 用途との位置付け

- リアルタイム YOLO は観戦中の補助表示・録画中の参考用。精度は nano モデルのため限定的
- 高精度な軌跡解析は録画済み動画に対する既存バッチ YOLO（`yolo.py`）を後日適用
- 録画は現状の MediaRecorder で生ストリームを保存、bbox は永続化しない

