# GPU 推論バックエンド整備（Tasks 1〜7）

## 変更日
2026-04-17

## 変更ファイル一覧

| ファイル | 種別 | 内容 |
|----------|------|------|
| `backend/cv/factory.py` | 修正 | OpenVINO 経路を追加（CUDA→OpenVINO→CPU→Mock） |
| `backend/cv/tracknet_openvino.py` | 新規 | OpenVINO ラッパー（tracknet/inference.py をProtocol適合） |
| `backend/cv/tracknet_runner.py` | 新規 | Ray タスクから呼ばれる TrackNet ランナー |
| `backend/cv/mediapipe_runner.py` | 新規 | Ray タスクから呼ばれる MediaPipe ランナー |
| `backend/pipeline/clips.py` | 新規 | ffmpeg クリップ抽出（NVENC / libx264 自動選択） |
| `backend/pipeline/statistics.py` | 新規 | 統計量算出エントリポイント（K10向け） |
| `backend/pipeline/cog.py` | 新規 | 重心算出エントリポイント（K10向け） |
| `backend/pipeline/shot_classifier.py` | 新規 | ショット分類エントリポイント（K10向け） |
| `backend/requirements.txt` | 修正 | mediapipe / pynvml を明示追加 |
| `scripts/setup_gpu.ps1` | 修正 | MediaPipe モデル自動 DL を追加 |

## バックエンド優先順（実装後）

```
factory.get_tracknet():
  SS_CV_MOCK=1  → MockTrackNet
  SS_USE_GPU=1  → CudaTrackNet        ← RTX 5060 Ti (X1 AI)
  失敗↓           OpenVINOTrackNet    ← iGPU / OpenVINO CPU
  失敗↓           CpuTrackNet         ← classical CV (K10でも動作)
  失敗↓           MockTrackNet
```

## Ray タスクとノード割り当て

| タスク | num_gpus | 担当ノード |
|--------|----------|-----------|
| run_tracknet | 1 | X1 AI (RTX 5060 Ti) |
| run_mediapipe | 1 | X1 AI (RTX 5060 Ti) |
| extract_clips | 0 (num_cpus=1) | K10 (ffmpeg libx264) |
| run_statistics | 0 (num_cpus=1) | K10 |
| calc_center_of_gravity | 0 (num_cpus=1) | K10 |
| classify_shots | 0 (num_cpus=1) | K10 |

## 修正前後の断絶箇所

修正前は `cluster/tasks.py` が以下の存在しないモジュールを呼んでいた：
- `backend.cv.tracknet_runner` → 今回作成
- `backend.cv.mediapipe_runner` → 今回作成
- `backend.pipeline.clips` → 今回作成
- `backend.pipeline.statistics` → 今回作成
- `backend.pipeline.cog` → 今回作成
- `backend.pipeline.shot_classifier` → 今回作成

## 検証
- `npm run build` でフロントエンドビルドエラーなし
- 全 Python ファイルの構文チェック (`ast.parse`) OK
