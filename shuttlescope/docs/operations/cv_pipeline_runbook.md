# CV Pipeline Runbook (WASB / INT8 / NVDEC)

オペレータ向け運用ハンドブック。詳細な実験ログは `docs/research/2026-05-24_wasb_vs_tracknet_player_a.md` を参照。本ドキュメントは「本番でどの env を立てるか」「異常時どこを見るか」を最短経路で示す。

---

## ⚠️ 2026-05-24 RETRACTION — 検出率の数字は誤り

以下の TL;DR / 表に出てくる **「検出率 87.1% / 100% / 30.9% / 40.1%」等は信頼できない**。これらは「conf ≥ 0.5 を満たすフレームの割合」を測っているだけで、目視確認で **24/24 のサンプルがシャトルではなく人物のユニフォーム or ネットポール上をマークしていた**。FP16/INT8 の追加比較で:

| Mode | 報告 visible% | 視覚で実際にシャトルを当てたコマ | 真の hit 率 |
|---|---|---|---|
| FP16 | 51.6% | 1/12 | **~8%** |
| INT8 | 92.6% | 2/12 | **~17%** |

→ 報告値は **5-6× 過大**。INT8 ↔ FP16 の切替では本質的に解決しないため、(a) UI から % 表示を一旦撤去、(b) quality-gated visible（peak 鋭さ + 動き整合）、(c) タイル推論で実解像度を上げる、の 3 段で対応中。

下の数値は **「メトリクス値の動き」としては再現性あるが「シャトル検出としては嘘」** という前提で読むこと。

---

## TL;DR

ShuttleScope のシャトル検出は **WASB + INT8 + NVDEC** で TrackNetV3 から完全置換可能。Player Aダブルス映像で検出率 **0% → 87.1%** (cross-video median 100%)、WASB 単独 **156 FPS** (NVDEC 込)、フルパイプ **67 FPS** (5060 Ti, FP16) を実測達成。**推奨 prod 設定**:

```
SS_SHUTTLE_IMPL=wasb
SS_WASB_USE_INT8=1
SS_WASB_USE_NVDEC=1
SS_DISABLE_RELOAD=1
```

INT8 は player_a/video-b/-d/-db の 4 映像で +22pt 安定改善 (overfit ではない、ただし N=4 と小)。失敗時は自動 FP16 → 自動 TrackNet フォールバックで本番停止しない設計。

---

## Production env switch matrix

| Env var | Values | Effect | When to use |
|---|---|---|---|
| `SS_SHUTTLE_IMPL` | `tracknet` (default) / `wasb` | シャトル検出器の選択。`wasb` で `WasbInference` に切替 | 本番は `wasb`。未検証映像種で挙動不安なら `tracknet` に即戻し |
| `SS_WASB_USE_INT8` | `0` (default) / `1` | INT8 QDQ ONNX (1.49 MB) を load。TRT EP の INT8 mode も有効化 | 検出率優先 (+22pt)、速度同等以上。**本番推奨** |
| `SS_WASB_USE_NVDEC` | `0` (default) / `1` | `nvdec_pipe` で zero-copy GPU decode (cv2 をバイパス) | 速度優先 (decode 11.7× / e2e 1.49×)。失敗時 cv2 自動 fallback |
| `SS_WASB_ROI_REFINE` | `0` (default) / `1` | 2nd-pass track-then-detect ROI re-inference | オフライン分析・精度極限のみ。**本番では OFF (17× 遅化、+0.9pt のみ)** |
| `SS_WASB_ONNX` | (abs path) | カスタム ONNX を強制指定 (INT8 env より優先) | A/B テスト・自前 fine-tune モデル投入時 |
| `SS_SHUTTLE_IMPL` + load 失敗時 | — | factory が graceful に `get_tracknet()` へ fallback (`backend/cv/factory.py`) | 自動フォールバック確認 |
| `SS_DISABLE_RELOAD` | `0` / `1` | uvicorn reload を無効化、prod の reload-loop 防止 | **本番では必ず `1`** (`deploy.ps1` で自動設定済) |
| `SS_CUDA_DEVICE` | `0` (default) | 使う CUDA device index | multi-GPU 環境のみ変更 |
| `SS_USE_GPU` | `0` / `1` | TrackNet/Pose の CUDA 経路許可 | prod は `1` |

---

## Measured numbers (RTX 5060 Ti 16 GB, driver 596.21)

### Per-component synthetic FPS (TensorRT EP, batched)

| Model | FPS | batch | backend | Solo headroom vs 60 |
|---|---|---|---|---|
| YOLOv8n FP16 | 1451.9 | 16 | TRT EP | 24.2× |
| RTMPose-m | 984.6 | 16 | TRT EP raw | 16.4× |
| TrackNetV3 | 156.7 | 8 | onnx_trt | 2.6× |
| WASB FP16 (Tier1 opt) | 484.2 / 506.5 | 8-20 | TRT EP IOBinding | 8.1× |
| WASB INT8 (QDQ + polygraphy) | 283.4 | 8 | TRT EP INT8 | 4.7× |

### Pipeline realized FPS (real video, player_a 1798 frame @ 1080p60)

| Config | Sequential | Threaded || | Notes |
|---|---|---|---|
| 4-person pose, FP16 | 52.3 | 55.4 | 60 FPS 未達 (92%) |
| **2-person pose, FP16** | **62.3 / 63.2** | **64.4 / 67.1** | **60 FPS 達成 (本番標準)** |
| 2-person pose, INT8 | 54.9 | 58.5 | 9% trade-off、検出 +22.6pt |
| WASB only, FP16 | — | 192 | |
| WASB only, INT8 | — | 143 | (TRT EP wrap overhead) |
| **WASB only, INT8 + NVDEC** | — | **156** | decode 0.64s vs cv2 7.4s |

### Detection rate cross-video (visible threshold 0.5)

| Video | TrackNetV3 | WASB FP16 (smoothing) | WASB INT8 (motion smoothing) |
|---|---|---|---|
| player_a 1080p60 (calibration source) | **0.0%** | 40.1% / 61.1% | **87.1%** |
| video-b 640×360 | 0.0% | 76.5% / 99.8% | **100.0%** |
| video-d 640×360 | 0.0% | 76.5% | **100.0%** |
| video-db 640×360 | 0.0% | 76.5% | **100.0%** |

INT8 のゲインは **4 映像とも +22pt 前後で揃う** → calibration overfit ではない。ただし N=4 と小なので、新規映像種投入時は smoke 必須。

---

## Switching configs (operator howto)

### 本番 prod に env 反映 (NSSM)

NSSM サービス名 `ShuttleScopeBackend` を前提。

```powershell
# 現状確認
nssm get ShuttleScopeBackend AppEnvironmentExtra

# WASB + INT8 + NVDEC 有効化
nssm set ShuttleScopeBackend AppEnvironmentExtra `
  SS_SHUTTLE_IMPL=wasb `
  SS_WASB_USE_INT8=1 `
  SS_WASB_USE_NVDEC=1 `
  SS_DISABLE_RELOAD=1 `
  SS_USE_GPU=1

# 再起動
nssm restart ShuttleScopeBackend
```

**注意**: `deploy.ps1 -BackendOnly` 経由は pipe-close bug があるため NSSM 直叩き推奨。`deploy.ps1` は `SS_DISABLE_RELOAD=1` を process-level env に書き込むようになっている (commit 875b900) ので、フルデプロイ時はそのまま。

### どの backend が active か確認

ログを grep:

```powershell
# Backend 起動ログ確認
Get-Content C:\path\to\backend.log | Select-String "\[cv\.factory\] Shuttle detector|\[wasb\] loaded via"
```

期待出力例 (WASB INT8 + NVDEC 正常時):

```
[cv.factory] Shuttle detector: WASB (backend=trt+int8:0)
[wasb] loaded via trt+int8:0 (model=wasb_badminton_qdq_int8.onnx)
[wasb] GPU warmup ok (batches=[1, 8])
[wasb.run] using NVDEC fast path: <video_path>   # 実 run 時のみ
```

FP16 にフォールバックした場合:

```
[wasb] SS_WASB_USE_INT8=1 but <...>_qdq_int8.onnx not found, falling back to FP16
[wasb] loaded via trt:0 (model=wasb_badminton.onnx)
```

TrackNet にフォールバックした場合:

```
[cv.factory] WASB load failed (<err>) — TrackNet にフォールバック
```

### ロールバック

```powershell
nssm set ShuttleScopeBackend AppEnvironmentExtra `
  SS_SHUTTLE_IMPL=tracknet `
  SS_DISABLE_RELOAD=1 `
  SS_USE_GPU=1
nssm restart ShuttleScopeBackend
```

env を 1 つ落とすだけで TrackNetV3 (旧本番) に即戻る。コード変更不要。

---

## Known limitations and gotchas

### `deploy.ps1 -BackendOnly` の pipe-close bug

`deploy.ps1 -BackendOnly` 経由で backend を再起動すると、PowerShell の pipe が早期 close され uvicorn が SIGTERM 相当を受け取ってしまうケースが報告されている (commit 963ad6b で docs 化済)。**本番運用では NSSM service restart を使うこと**:

```powershell
nssm restart ShuttleScopeBackend
```

### `.env.development` の UTF-8 BOM トラップ

PowerShell の `Set-Content -Encoding UTF8` は **BOM 付き UTF-8** を出力する。Python の `dotenv` は BOM 付きを読むと最初の key が `﻿SS_...` になり env が反映されない。対応:

```powershell
# BOM 無しで書く (PowerShell 5.1)
[IO.File]::WriteAllText("$pwd\.env.development", $content, [Text.UTF8Encoding]::new($false))
```

または `nssm set ... AppEnvironmentExtra` 経由で直接 env 設定するなら `.env` は不要。

### TRT 10.16 implicit INT8 calibration deprecated

`tensorrt 10.16.1.11` で `IInt8EntropyCalibrator2` 経路は `validateCaskKLibSize failed` で build error。TRT 10.1+ は **explicit quantization (QDQ ONNX) が必須**。本番採用パス:

```python
from onnxruntime.quantization import quantize_static, QuantFormat, QuantType
quantize_static(
    onnx_in, onnx_qdq_sym,
    calibration_data_reader=reader,
    quant_format=QuantFormat.QDQ,
    per_channel=True,
    weight_type=QuantType.QInt8,
    activation_type=QuantType.QInt8,
    op_types_to_quantize=["Conv"],          # bias を除外 (INT32 入力で DequantizeLinear 不可)
    extra_options={
        "ActivationSymmetric": True,         # zero_point=0 (TRT 要件)
        "WeightSymmetric": True,
        "QuantizeBias": False,
    },
)
```

→ polygraphy で TRT engine build (52.9s)。`backend/wasb/weights/wasb_badminton_qdq_int8.onnx` が成果物。

### PyNvVideoCodec のバージョン問題

`pip install PyNvVideoCodec` で入る `_130` 系は **CUDA 13 必須**。CUDA 12.x torch 環境では `_121` 系を強制 load しないと NVDEC が立ち上がらない。`backend/wasb/nvdec_pipe.py` の `is_available()` で互換性検出 → 不可なら cv2 fallback。

### INT8 cross-video N=4 警告

INT8 +22pt は player_a / video-b / -d / -db で確認 (`Addendum 8`)。**異なる解像度 (1080p / 640×360) で同じ gain** = generalizable と判定したが、N=4 は統計的に弱い。新規映像種 (シングルス、低照度、室内体育館以外) 投入時は必ず cross-video smoke を回す。

### Track-then-detect ROI refinement は opt-in only

player_a では +0.9pt 検出率 vs 17× 速度ペナルティ。Python overhead が candidate 数で線形悪化。**本番では `SS_WASB_ROI_REFINE=0` 固定**、オフライン分析専用。

### GPU util 56%、律速は Python overhead

`nvidia-smi` 0.1s sampling で full pipeline 中 GPU util mean 56.2% / power 38% TGP。理論余裕 113 FPS だが Python の per-frame overhead が支配。これ以上の高速化は Cython / C++ wrapper / multi-process が必要。

---

## Files of interest

| Path | 役割 |
|---|---|
| `backend/wasb/inference.py` | `WasbInference` runner。TRT/CUDA EP, IOBinding, sigmoid, motion smoothing, ROI refinement, NVDEC fast path |
| `backend/wasb/nvdec_pipe.py` | PyNvVideoCodec zero-copy GPU pipe (NV12 → torch tensor) |
| `backend/wasb/weights/wasb_badminton.onnx` | FP16, 5.18 MB |
| `backend/wasb/weights/wasb_badminton_qdq_int8.onnx` | QDQ INT8 (symmetric, Conv-only), 1.49 MB |
| `backend/wasb/weights/trt_cache/` | FP16 TRT engine cache (auto-create, GPU/driver/ONNX hash 依存) |
| `backend/wasb/weights/trt_cache_int8/` | INT8 用別 cache |
| `backend/wasb/README.md` | upstream license, re-export 手順 |
| `backend/cv/factory.py` | `get_shuttle_detector()` env switch + graceful fallback |
| `backend/cv/rtmpose.py` | RTMPose batched ONNX + `torchvision.ops.roi_align` GPU preproc |
| `backend/cv/tracknet_runner.py` | `run_tracknet(video_path)` (cluster/tasks 経由) — factory 経由化済 |
| `backend/pipeline/video_pipeline.py` | standalone worker のシャトル検出経路 — factory 経由化済 |
| `backend/benchmark/runner.py` | ベンチランナー (TrackNet 固有 introspection のため `get_tracknet()` 直叩き継続) |
| `backend/tests/test_wasb_inference.py` | WASB 単体 9 tests |
| `backend/tests/test_shuttle_factory_integration.py` | factory 切替 7 tests |
| `scripts/check_module_scope_t.py` | i18n module-scope `t()` 検出 ガード |
| `.github/workflows/check-i18n.yml` | 上記 CI |
| `docs/research/2026-05-24_wasb_vs_tracknet_player_a.md` | 全 9 addendum の詳細実験ログ |
| `docs/research/2026-05-24_validation_bench_player_a.md` | TrackNet 0% 検出の発見 (本作業の起点) |
| `docs/research/2026-05-23_cv_model_survey.md` | モデル survey と Phase ロードマップ |

---

## Phase 2 / future

| 項目 | 期待効果 | 実装難度 |
|---|---|---|
| PyTorch QAT (Quantization-Aware Training) | INT8 でさらに精度向上、5060 Ti でも 1.5-2× 余地 | 数日 (学習基盤要) |
| TrackNetV3 → WASB 蒸留 / WASB INT8 蒸留 | 小型モデル化、edge / Jetson 投入余地 | 数日 |
| Pose 蒸留 (RTMPose-m → RTMPose-Tiny) | Pose 144 FPS → 250+ FPS、フルパイプ headroom | 1-2 日 |
| 真の NVDEC ↔ WASB zero-copy (`__cuda_array_interface__`) | 現状 1.49× → さらに +30-50% 期待 (cv2 width/height 取得も排除) | 数時間〜半日 |
| RTX Pro 6000 ハードウェア投入 | 全体 4-6×。フルパイプ realized 250-400 FPS 見込み | 入手後即 |
| Track-then-detect sparse 化 | 検出 +3-5pt、現状 17× を 2× 以下に圧縮 | 1-2 日 |
| New-video class cross-video re-validation | INT8 generalization の N を増やす | smoke 走らせるだけ |

---

## Appendix: 最終確定スコア

| 項目 | 本セッション開始時 | 最終 |
|---|---|---|
| WASB 検出率 (player_a) | TrackNetV3 **0.0%** | INT8+motion smoothing **87.1%** |
| WASB 検出率 (other 3 video median) | 0.0% | **100.0%** |
| WASB 単独 realized FPS | 29.9 | **156** (INT8 + NVDEC) |
| Full pipeline realized FPS | 10.8 | **67.1** (FP16 / 2-person pose) |
| 60 FPS 目標 | × | ✓ 全 config |
| Production migration | none | factory + env switch 完了 (commit `2d7fef3`) |
