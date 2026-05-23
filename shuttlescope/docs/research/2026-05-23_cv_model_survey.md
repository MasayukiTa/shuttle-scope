# Badminton CV/Pose/Action Model Survey — 2026-05-23

調査範囲: 既存 TrackNetV3 に加え、シャトル検出・姿勢推定・ストローク認識・コートキャリブレーションのモデル群について **権利 / 動作可能性 / 推論律速** を整理。

## Executive Summary

- **30fps @ 1080p / 2-player 達成可能** on RTX 5060 Ti, FP16 TensorRT 前提で ~28 ms/frame
- **CoachAI / ShuttleSet / ShuttleNet** はコード MIT だがデータセットライセンス明記なし → **NTU 連絡が前提条件**
- **TVCalib はサッカー専用、バドミントン不適** — 既存自前キャリブで継続
- **TemPose 公式コード未公開** → PoseC3D (Apache-2.0) で代替し、ShuttleSet 承認後 fine-tune
- **TrackNetV3 → ShuttleNet 蒸留は不適** (異タスク)。代替: 共有 backbone joint multi-task or pseudo-label 融合

## Pipeline Latency (RTX 5060 Ti, FP16 TRT, 1080p, N=2 player)

| Stage | Model | ms | VRAM (MB) | License |
|---|---|---|---|---|
| Person Detect | YOLOv11-s | 4-5 | 400 | AGPL-3.0 (要確認) |
| Pose ×N | RTMPose-m | 8-14 | 600/person | Apache-2.0 |
| Shuttle | TrackNetV3 (TRT) | 3-5 | 1,200 | MIT |
| Action | TemPose / PoseC3D | 5-8 | 800 | (PoseC3D Apache-2.0) |
| **合計** | | **20-32** | **~3,000** | |

予算 33.3 ms (30fps) 内。Pro 6000 で 4-6× 加速見込み。

## 採用判断マトリクス

| Model | License | TRT | Badminton 対応 | 判断 | Phase |
|---|---|---|---|---|---|
| TrackNetV3 | MIT | ✅ INT8 | ✅ | **KEEP** | 0 (現状) |
| WASB-SBDT | MIT | ⚠️ 要検証 | ✅ | TEST | 2 |
| ViTPose | Apache-2.0 | ⚠️ 遅め | ✅ | 代替案 | 1 (optional) |
| **RTMPose** | Apache-2.0 | ✅ MMDeploy | ✅ | **ADOPT** | 1 |
| MonoTrack | ❓ | ❌ | ✅ (3D) | SKIP | — |
| TemPose | ❓ コード無 | ⚠️ | ✅ | TRY/PoseC3Dフォールバック | 1 |
| **PoseC3D** | Apache-2.0 | ✅ | 要 fine-tune | **ADOPT** | 1 |
| CoachAI (code) | MIT | — | ✅ | BLOCKED (data 待ち) | 3 |
| ShuttleSet | ❓ | — | ✅ | BLOCKED | 3 |
| ShuttleNet | MIT? | — | ✅ | BLOCKED | 3 |
| TVCalib | MIT | ⚠️ | ❌ サッカー専用 | **SKIP** | — |

## NTU 連絡テンプレ (英文)

```
Subject: ShuttleSet Data Usage & Commercial Deployment Inquiry

Dear Prof. [Lab Lead, NTU Advanced Database System Lab],

We are developing a badminton analysis system (ShuttleScope) and wish to:
1. Use ShuttleSet for model training and evaluation
2. Redistribute trained models (e.g., fine-tuned action recognizers) to end users
3. Publish research using ShuttleSet benchmarks

Questions:
- Is ShuttleSet under CC-BY-NC / CC-BY-SA / MIT / other?
- Are commercial applications permitted?
- Can we redistribute weights from models trained on ShuttleSet?
- Is there a formal Data Use Agreement?
- If commercial use prohibited, can we negotiate a separate license?

Happy to acknowledge CoachAI in product and academic publications.

Regards,
[Name / Team]
```

## Distillation 方針

**TrackNetV3 (軌跡) → ShuttleNet (次手予測) の直接蒸留は不適** (タスク不一致, KL 構成不能)。

代替案:
- **A. Joint multi-task** — 共有 Transformer encoder + 軌跡 head + 行動 head, `L = λ₁ L_traj + λ₂ L_action`. 要 ShuttleSet
- **B. 二段パイプ (現状継続)** — TrackNetV3 → RTMPose → PoseC3D/TemPose 独立段。互換性高、誤差カスケード
- **C. Pseudo-label 融合** — TrackNetV3 軌跡特徴を ShuttleNet 入力に concat、再 fine-tune

優先: B (Phase 1) → C (ShuttleSet 承認後) → A (中長期)

## Phased Roadmap

### Phase 0 (NOW)
- [ ] NTU 連絡メール送付
- [ ] (待ちの間に Phase 1 並列着手)

### Phase 1 (週 1-2)
- [ ] RTMPose を `backend/pose/` に組み込み (MMDeploy で ONNX→TRT)
- [ ] PoseC3D を `backend/action/` に組み込み (MMAction2 from Apache-2.0)
- [ ] フルパイプ 30fps 検証 on 5060 Ti
- [ ] YOLOv11 → RTMPose → TrackNetV3 → PoseC3D の連結 stub
- [ ] 既存 `backend/tracknet/` 抽象に沿って `BadmintonModel` 基底を導入

### Phase 2 (週 3-4)
- [ ] WASB-SBDT ONNX 変換ベンチ → TrackNetV3 比較
- [ ] Pro 6000 ベンチ (入手次第)
- [ ] Multi-stream GPU 並列化 (CUDA streams)

### Phase 3 (週 5-8, 条件付き)
- [ ] ShuttleSet 取得 (承認後) → PoseC3D/TemPose fine-tune
- [ ] ShuttleNet stroke forecast 統合
- [ ] Joint multi-task 試作 (Option A)

### Phase 4 (週 9-12)
- [ ] INT8 量子化 (TRT calibration on 1000 frames)
- [ ] Multi-GPU 分散 (Pro 6000 + 5060 Ti 投入時)

## Open Questions
1. **CoachAI/ShuttleSet ライセンス** — 最大ブロッカー
2. **TemPose コード** — 著者問い合わせ or PoseC3D 代替
3. **YOLOv11 ライセンス** — AGPL-3.0 のため商用利用に制約。代替に YOLOX (Apache-2.0) も検討
4. **MonoTrack LICENSE** — 低優先 (TrackNetV3 で間に合う)
5. **2人インタラクションモデル** — TemPose が単選手単位なら、ラリー文脈モデルが別途必要か

## 参照
- TrackNetV3: https://github.com/qaz812345/TrackNetV3 (MIT) / TRT fork https://github.com/nickluo/TrackNetV3
- WASB-SBDT: https://github.com/nttcom/WASB-SBDT (MIT, BMVC 2023)
- RTMPose / MMPose: https://github.com/open-mmlab/mmpose (Apache-2.0)
- ViTPose: https://github.com/ViTAE-Transformer/ViTPose (Apache-2.0)
- PoseC3D / MMAction2: https://github.com/open-mmlab/mmaction2 (Apache-2.0)
- CoachAI / ShuttleSet / ShuttleNet: https://github.com/wywyWang/CoachAI-Projects (code MIT, data unknown)
- TemPose: CVPR 2023 Workshops paper, no public repo
- MonoTrack: https://github.com/jhwang7628/monotrack (license unknown)
- TVCalib: https://github.com/mm4spa/tvcalib (MIT, soccer-only)

## Status
- Drafted: 2026-05-23
- Phase 1 着手可、Phase 3 は NTU 承認待ち
