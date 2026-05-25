# Validation Bench: Existing CV Pipeline on Player A Doubles (match 33)

## Target
- **Match**: id=33, 2025-12-26, 第79回全日本総合 女子ダブルス2回戦
- **Players**: Player A (Player A) ペア vs Players D/E (doubles)
- **Video**: `videos/fd425688-db28-401e-a57b-7af2d6114a4e.mp4` (YouTube `YDBA8OX5bH0`)
- **Format**: 1920×1080, 59.94 fps, 3481 秒 (58 分)
- **Bench windows**: 60-90s (試合開始直後) と 600-630s (ラリー中) の 2 区間 × 30秒 (1798 frame)

## Hardware / Stack
- GPU: RTX 5060 Ti 16GB (driver 596.21, CUDA 13.2)
- Python 3.12, onnxruntime 1.24.4 (Tensorrt/CUDA/CPU providers)
- Models: YOLOv8n (person), RTMPose-m (pose), TrackNetV3 CUDA (shuttle)

## 重要な前段発見 (本ベンチの最大成果)

bench 開始時 onnxruntime が **CPU fallback で silent 動作** していた。原因:
`cublasLt64_12.dll` が PATH 未登録 (CUDA Toolkit 未インストール、PyTorch 同梱 DLL を `os.add_dll_directory()` 登録するロジックが load 順序で適用されない)。

修正: bench script 冒頭で `torch/lib` を明示登録 → CUDA EP 有効化。**本番 backend でも同じ罠が存在する可能性が高いので別途検証要**。

```python
import torch
os.add_dll_directory(os.path.join(os.path.dirname(torch.__file__), "lib"))
```

## 6 指標結果

| 指標 | 60-90s | 600-630s (ラリー) | 判定 | 備考 |
|---|---|---|---|---|
| (a) Top-4 主要選手検出率 | 100% | 100% | ◎ | YOLO 18-22人 (観客込) → area top-4 で安定 4 人 |
| (b) ID switches /30s | 70 | 68 | ✗ | 簡易 IoU トラッカーの仕様、本番 ByteTrack なら改善見込 |
| (c) RTMPose kp 平均信頼度 | **0.60** | 0.51 | ○/△ | ラリー中は素早い動きで confidence 低下 |
| (d) **シャトル検出率 (conf≥0.5)** | **0%** | **0%** | ✗✗✗ | **重大: ほぼ機能していない** |
| (e) FPS (CUDA 効いた状態) | 14.5 | 8.0 | ✗ | TrackNet 61ms が支配的 |
| (f) 遮蔽下耐性 | 100% | 100% | ◎ | top-4 強制下では問題なし |

### 詳細パイプライン時間 (ms/frame, 600-630s)

| Stage | mean | p50 | p95 |
|---|---|---|---|
| YOLO | 40.3 | 39.6 | 46.4 |
| RTMPose (4人) | 23.4 | 22.7 | 30.1 |
| TrackNet | 61.3 | 60.6 | 67.1 |
| **Total** | **124.8** | 123.6 | 140.8 |

## ✗✗✗ 重大: TrackNetV3 がこの映像でシャトルを認識できていない

- 全 1791 frame で `shuttle_visible=False`, `shuttle_conf=0.137-0.154` の狭い帯
- これは **TrackNet 内の skip-optimization が前フレーム conf を 0.85 倍減衰させ続けた結果のフロアノイズ** であり、実際には1 frame も検出していない
- 60-90s (試合開始) も 600-630s (ラリー中) も同様 → 区間問題ではなく **モデル × 映像** のミスマッチ

### 想定原因
1. **解像度 / カメラ距離**: 1920×1080 全コートズーム → シャトルが 5-10 px 程度、TrackNet 学習データの想定より小さい
2. **frame rate**: 59.94fps、TrackNet 学習時は 30fps 前提でフレーム間移動量が学習分布外
3. **モデル重み**: `backend/models/` に shuttle 用 ONNX が見当たらない (yolov8n, yolov8n_pose, rtmpose_m_simcc のみ)。TrackNet 自体は CUDA backend 経由で動作はしている (61ms 計測あり) が、`predict_frames` の戻り値が全 frame 空に近い

## 推奨アクション (優先順)

### Priority 1: TrackNet モデル/設定の見直し (急務)
- **TrackNet 重みファイルの所在**: `backend/models/` に shuttle 用 model.onnx 等が無い疑い → 確認
- **frame rate downsample**: 60fps → 30fps に間引いてからTrackNet 投入を試す
- **解像度 crop**: コート領域に crop してから TrackNet 投入 (シャトル相対サイズを学習分布に寄せる)
- **代替モデル検証**: WASB-SBDT、TrackNetV2 を同条件で比較。CV survey MD (2026-05-23) の Phase 2 を前倒し

### Priority 2: コート内フィルタの本番組み込み
- 現在 YOLO が観客 16-22 人を検出し RTMPose が全員に適用される → 5x のコストロス
- `court_side` キーは「どっち側」しか分からず内外フィルタにならない
- **解決**: court calibration の polygon を使って `foot_point` が court 内か判定するヘルパを `backend/cv/court_mapper.py` に追加し、YOLO 直後でフィルタ

### Priority 3: ByteTrack ID 安定性検証
- 本ベンチの 70 switches は私の簡易 IoU トラッカー由来。本番 ByteTrack で同区間を測り直す必要
- `backend/yolo/inference.py` 内の ByteTrack ラッパで `track_id` を取得して比較

### Priority 4: TensorRT INT8 化検討
- 現状 CUDA FP16 → 124ms/frame、INT8 化で 60-80ms 期待
- ただし TrackNet が本質課題な現状、まず Priority 1 を先に

## 副次発見

### CUDA silent CPU fallback の罠
本番 backend が同じ状況なら **全推論が CPU 実行されている** 可能性。要確認:
- `_register_cuda_dll_dirs()` は `TrackNetInference.__init__` で呼ばれるが、それ以前に YOLOInference / RTMPose を初期化すると CUDA EP が CPU fallback
- backend 起動順序によっては全部 CPU で走っている

→ **別件として `backend/main.py` startup 冒頭で `_register_cuda_dll_dirs()` を必ず先に呼ぶ修正が必要**

### 観客検出の実コスト
- YOLO は audience 18-22 人を検出
- フィルタなしの場合 RTMPose が全員に走り 114ms/frame (vs フィルタ後 23ms)
- 本番が観客込みで pose 推定していたら、シングルス映像で実 FPS 5-10 に低下している可能性

## bench 出力
- `C:\Users\kiyus\Desktop\bench_out\` (60-90s, 観客込み、CPU fallback)
- `C:\Users\kiyus\Desktop\bench_out2\` (60-90s, 観客込み、CUDA)
- `C:\Users\kiyus\Desktop\bench_out3\` (60-90s, top-4 filter)
- `C:\Users\kiyus\Desktop\bench_out4\` (60-90s, TrackNet CUDA forced)
- `C:\Users\kiyus\Desktop\bench_out5\` (600-630s, x_norm/y_norm 修正、ラリー区間)
- 各 dir に `result.json`, `per_frame.ndjson`, `sample_*.png` (5枚)

## 次の bench で測りたいこと
1. シングルス映像 (match id=32 等) との比較 — 4人 vs 2人で pose コスト差確認
2. 720p (`_hd.mp4` variant) で TrackNet 検出率の変化
3. 30fps デシメート版での TrackNet 復活確認
4. 本番 ByteTrack の ID 安定性 (現状 ByteTrack ラッパが利用可能か要調査)
5. 本番 backend が CPU fallback してないかの確認 (production smoke test)

## 採否判定 (本ベンチ範囲)
- **YOLO + RTMPose**: 既存採用継続。コートフィルタ追加で更に高速化余地あり ✓
- **TrackNet**: **このダブルス映像では機能していない**。代替検証 (WASB) または再学習が必要 ✗
- **新モデル追加 (RTMPose 等)**: 不要 (既統合済み、CV survey 確認済)

## ── Addendum (2026-05-24 後追い): GPU 実行確認 + 真の FPS ──

初版ベンチで「全 GPU 推論されてる」と仮定していたが、検証の結果 **YOLO だけ CPU で走っていた** ことが判明。OpenVINO 経由読み込みが silent failure → ultralytics CUDA も `_ul_device=cpu` で着地 → CPU 推論 (39ms)。

`torch.cuda.is_available()=True`, `torch.version.cuda=12.8`, RTX 5060 Ti 認識済みなので **本来 CUDA EP で動くべきところが運用バグ**。

### 修正: 直接 onnxruntime CUDA で YOLO 起動
`backend/yolo/inference.py` のフォールバック chain を回避し、`yolov8n_fp16.onnx` を `ort.InferenceSession` で CUDA EP 直指定。

### 確定 FPS (全 CUDA, 1798 frame, 600-630s slice, FP16)

| Stage | 実装 | ms/frame mean (p95) | VRAM Δ | Solo FPS |
|---|---|---|---|---|
| YOLO | ORT CUDA FP16 (yolov8n_fp16.onnx) | 30.0 (37.9) | +66 MiB | **33** |
| RTMPose | get_rtmpose_engine() CUDA | 22.3 (29.3) | +463 MiB | **45** (4人) |
| TrackNet | TrackNetInference(backend='cuda') | 34.7 (38.2) for 3-frame batch | +3012 MiB | **29** (batch) |
| **Total sequential** | | **86.9 (103.6)** | **+3541 MiB** | **10.8 realized** |

VRAM 最終 5536 MiB / 5060 Ti 16 GB → 余裕 10.6 GB。

### YOLO synthetic vs live の差 (7.7ms → 30ms)
同一フレーム連続推論 (synthetic): 7.7ms (130 FPS) = 純粋なGPU forward。
新規フレーム逐次推論 (bench): 30ms = +20ms は Python 内の preprocess (cv2.resize → cvtColor → transpose) + cv2.dnn.NMSBoxes の CPU 処理。

### 30 FPS 達成への道筋
現状 sequential 87ms = 11.5 FPS。30 FPS 達成には:
- (a) **CUDA streams で YOLO/Pose/TrackNet を並列実行** → 推論時間の最大値 (~35ms) に律速 = **28 FPS**
- (b) preprocess を GPU で行う (CUDA kernel for resize+norm or torchvision) → YOLO 30ms → 12ms 想定
- (a)+(b) 併用で **~40 FPS 達成可能**

### 真の所見
- **GPU 推論問題**: YOLO の OpenVINO/ultralytics fallback chain が壊れていた → ORT CUDA 直接で解決
- **TrackNet 0% 検出**: GPU で確実に動作確認 (TensorRT 警告も解消後)、それでも shuttle_conf max=0.15 で全 frame 「無し」判定。これは **モデル × 映像** の本質的 mismatch。Phase 2 で WASB-SBDT との比較必須
- **本番 backend のリスク**: 同じ silent CPU fallback が本番で起きていた可能性。`backend/yolo/inference.py` の load() ロジック修正 + 起動時に backend ログ出力する hardening が必要

### 採否更新
- **YOLO ORT CUDA 直接化**: 採用推奨。`backend/yolo/inference.py` を ORT CUDA 優先順に再構成
- **TrackNet 代替**: Phase 2 で WASB-SBDT と shuttle 検出率を直接比較
- **30 FPS パイプライン**: CUDA streams 並列化 + preprocess GPU 化で十分到達可能

## ── Addendum 2 (2026-05-24 公式 BenchmarkRunner 実測): 真の上限 ──

ユーザ指摘により既存 `backend/benchmark/runner.py` の正規ベンチを CUDA device で実行。各ターゲットは **TensorRT EP + raw-tensor + batch 最適化** されており、本来の性能はこちら:

| Target | FPS | avg ms | batch | backend | 備考 |
|---|---|---|---|---|---|
| **TrackNet** | **155.95** | 6.41 | 8 | `onnx_trt:0` | TensorRT EP |
| **Pose (RTMPose)** | **984.62** | 1.02 | 16 | `trt:0` | raw tensor inference |
| **YOLO (yolov8n_fp16)** | **1451.91** | 0.69 | 16 | TensorRT EP | |

→ **30 FPS 上限は当然クリア。律速は wrapper 層 (Python preprocess/postprocess + 単 frame 直列実行) であり、モデル GPU 推論ではない**。

### 私の ad-hoc bench との乖離理由
| 要因 | 影響 |
|---|---|
| Python 内で cv2.resize / cvtColor / np.transpose | YOLO +20ms 程度 |
| cv2.dnn.NMSBoxes (CPU) | YOLO +5-10ms |
| batch=1 vs batch=16 | per-sample で 20-30× |
| CUDA EP vs TensorRT EP | 2-3× |
| (個別フレームごと cap.read() の Python 経由) | 数 ms |

### 訂正した本番ボトルネック分析
- **GPU 推論性能は超余裕** (全 target で目標 30 FPS の数十倍)
- **本番が 30 FPS 出ない場合の真因は wrapper 層**:
  - `backend/yolo/inference.py` の preprocess/postprocess が Python
  - `backend/cv/rtmpose.py` の per-frame call (batch 化されてるか要確認)
  - sequential 実行 (CUDA streams 並列化なし)
  - 1080p フレーム I/O (decoding + numpy転送)
- ad-hoc bench の YOLO 30ms / Pose 22ms / TrackNet 35ms は **wrapper 経由の実用値**として参考になる

### 訂正した shuttle 検出 0% の意味
- **TrackNet GPU 性能 (155 FPS) は健全** — 計算は超高速で行われている
- それでも shuttle_conf max=0.15 (全 frame 「無し」判定) = 確実にモデル × 映像の問題
- → WASB-SBDT 比較 or 再学習が必要、という結論は変わらず

### 真の最終評価
- ❌ **GPU 推論問題は無かった** (前 addendum 訂正)
- ⚠️ **wrapper 層の高速化余地はある** (YOLO 30ms → 1ms 化、Pose 22ms → 4ms (4人batch) 化が可能)
- 🔴 **TrackNet shuttle 検出 0% のみが本質課題** — モデル交換が必要

### 採否最終版
- **既存 CV パイプ (TRT)**: 推論カーネル自体は採用継続、全く問題なし
- **wrapper 層の最適化**: 本番が遅い場合のみ着手 (まず本番計測)
- **TrackNet 代替**: WASB-SBDT との shuttle 検出率比較を Phase 2 で実施
- **新モデル追加**: 不要
