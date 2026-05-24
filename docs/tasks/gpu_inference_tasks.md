# GPU 推論バックエンド整備タスク（5060 Ti 対応）

## 作成日
2026-04-17

## 背景
- RTX 5060 Ti（eGPU）が X1 AI に接続される
- GMKtec K10（CPU専用ワーカー）との Ray クラスタ構成
- 現状は `factory.py` が Mock→CUDA→CPU のみで **OpenVINO 経路が断絶**
- `cluster/tasks.py` が呼ぶランナーモジュールが**すべて未存在**

## ノード役割分担

| ノード | GPU | 担当タスク |
|--------|-----|-----------|
| X1 AI (ヘッド) | RTX 5060 Ti | TrackNet / MediaPipe 推論 (num_gpus=1) |
| GMKtec K10 | なし | クリップ抽出 / 統計 / 重心 / ショット分類 (num_cpus=1) |

## 推論バックエンド優先順（設計）

```
factory.get_tracknet():
  SS_CV_MOCK=1      → MockTrackNet
  SS_USE_GPU=1      → CudaTrackNet  (torch + RTX 5060 Ti)
  ↓ fallback         OpenVINOTrackNet (openvino + Intel iGPU / CPU)
  ↓ fallback         CpuTrackNet  (classical CV, K10でも動作)
  ↓ fallback         MockTrackNet

factory.get_pose():
  SS_CV_MOCK=1      → MockPose
  SS_USE_GPU=1      → CudaPose  (MediaPipe GPU delegate)
  ↓ fallback         CpuPose  (MediaPipe CPU)
  ↓ fallback         MockPose
```

## タスク一覧

### Task 1: `cv/tracknet_openvino.py` 作成
OpenVINO バックエンドを `TrackNetInferencer` Protocol に適合させるラッパー。
`tracknet/inference.py` の `TrackNetInference` を薄くラップする。

**ファイル:** `backend/cv/tracknet_openvino.py` (新規)

---

### Task 2: `cv/factory.py` — OpenVINO 経路追加
CUDA → OpenVINO → CPU の 3 段フォールバックにする。

**ファイル:** `backend/cv/factory.py` (修正)

---

### Task 3: ランナーモジュール作成
`cluster/tasks.py` が呼ぶが存在しない 2 ファイルを作成。
factory を通じて正しいバックエンドを使う。

**ファイル:**
- `backend/cv/tracknet_runner.py` (新規)
- `backend/cv/mediapipe_runner.py` (新規)

---

### Task 4: `pipeline/clips.py` 作成
K10 で動作するクリップ抽出。`SS_USE_GPU=1` 時は ffmpeg NVENC を使用。

**ファイル:** `backend/pipeline/clips.py` (新規)

---

### Task 5: K10 向けパイプラインモジュール作成
統計/重心/ショット分類の薄いエントリポイント。
実ロジックは `cv/` 側の既存実装を呼ぶ。

**ファイル:**
- `backend/pipeline/statistics.py` (新規)
- `backend/pipeline/cog.py` (新規)
- `backend/pipeline/shot_classifier.py` (新規)

---

### Task 6: `requirements.txt` 整備
torch / pynvml / mediapipe を明示。

**ファイル:** `backend/requirements.txt` (修正)

---

### Task 7: `setup_gpu.ps1` — MediaPipe モデル自動 DL 追加
`pose_landmarker_lite.task` を手動 DL しなくて済むようにする。

**ファイル:** `scripts/setup_gpu.ps1` (修正)

---

## 検証チェックリスト（5060 Ti 到着後）

```powershell
# 1. ドライバ確認
nvidia-smi

# 2. CUDA 動作確認
$env:SS_USE_GPU=1
python -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# 3. OpenVINO GPU 確認
python -c "from openvino.runtime import Core; print(Core().available_devices)"

# 4. factory 経路確認
python -c "
from backend.cv.factory import get_tracknet, get_pose
t = get_tracknet(); print('TrackNet:', type(t).__name__)
p = get_pose();     print('Pose:', type(p).__name__)
"

# 5. MediaPipe GPU 確認
$env:SS_USE_GPU=1
python -c "from backend.cv.pose_cuda import CudaPose; CudaPose()"

# 6. Ray クラスタ確認（K10 接続後）
python -c "import ray; ray.init('ray://192.168.100.1:10001'); print(ray.cluster_resources())"
```

## TrackNet 本物の重みロード（TODO: 重み入手後）

`backend/cv/tracknet_cuda.py:46` の TODO を完了するには:
1. TrackNetV2 の学習済み重み (`.pt`) を `backend/cv/models/tracknet_v2.pt` に配置
2. TODO コメント内のコード (`self._model = TrackNetV2()...`) をアンコメント
3. `_run_torch()` のヒートマップ出力形状をモデルに合わせて調整
