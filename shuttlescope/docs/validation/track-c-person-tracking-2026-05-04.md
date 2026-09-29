# Track C: Person Tracking Overhaul (5060Ti) — 2026-05-04

ベース計画: `private_docs/2026-05-04_person_tracking_overhaul_plan.md`
完了: C1 〜 C5 全タスク

| # | 項目 | ファイル | テスト |
|---|---|---|---|
| C1 | TrackNet 本重み配備 verify | `backend/main.py` 内 `/api/health/cv` 追加 | (prod runtime verify) |
| C2 | RTMPose-m インテグレーション | `backend/cv/rtmpose.py` (新規) | `test_rtmpose.py` 7/7 |
| C3 | SwingDetector | `backend/cv/swing_detector.py` (新規) | `test_swing_detector.py` 7/7 |
| C4 | Hitter Attribution 3 段階フォールバック | `backend/cv/hitter_attribution.py` (新規) | `test_hitter_attribution.py` 8/8 |
| C5 | NetAwareDetector + CourtBoundedFilter | `backend/cv/detection_hardening.py` (新規) | `test_detection_hardening.py` 13/13 |
| **C 合計** | | | **35 件 pass** |
| 全 Track A+C+regression | | | **143 passed, 4 skipped** |

## 設計方針

各モジュールとも **graceful degradation**:
- 重みファイルやライブラリ (mmpose / onnxruntime) が無い環境でも import エラーを起こさない
- prod の 5060Ti では実推論が動き、CI/dev では空 keypoints などのスタブで動作継続
- `/api/health/cv` で prod 上の選択 backend を確認可能 (TrackNet, YOLO, RTMPose)

## ライブパイプライン統合

C2/C3/C4/C5 はモジュール単位で完成しているが、**まだバッチ YOLO/TrackNet パイプラインに wire していない**。
理由:
- 一気に wire すると問題切り分け困難
- 5060Ti 上で各モジュール単独 smoke 確認したのち順次 integrate するのが安全

次工程 (本書のスコープ外):
1. prod 上で `/api/health/cv` 叩いて backend 選択を確認 (C1)
2. RTMPose 重み (`backend/models/rtmpose_m_simcc.onnx` 等) を prod に配備
3. `routers/yolo.py` のバッチパイプ末尾で `RTMPoseEngine.infer` 呼出 → `SwingDetector.process_frame` → `attribute_hitter` の順で連鎖
4. `candidate_builder.py` の hitter 推定を `attribute_hitter` で置換 (元ロジックは fallback)

## Forward-compat 整理

| Hook | 提供 | 利用予定 |
|---|---|---|
| `IdentityGraph.inject_pose_features(label, kp)` (Track A3) | ✅ | RTMPose 結果を identity に紐付け |
| `IdentityGraph.get_confidence(label)` (Track A3) | ✅ | Track B ConfidenceCalibrator (Platt) 入力 |
| `CourtAdapter.for_match(match_id)` (Track A2) | ✅ | NetAwareDetector / CourtBoundedFilter で使用済 |
| `RTMPoseEngine.infer(frame, dets) → List[PoseResult]` (Track C2) | ✅ | SwingDetector 入力 |
| `SwingDetector.process_frame → SwingEvent` (Track C3) | ✅ | attribute_hitter Priority 1 入力 |
| `attribute_hitter(...) → HitterAttribution` (Track C4) | ✅ | candidate_builder 統合候補 |

## 受け入れ基準

- [x] 全モジュールがユニットテスト pass
- [x] 既存 backend pytest に regression なし (143 passed, 4 skipped)
- [x] graceful degradation: 重み/依存無し環境でも import エラーなし
- [x] prod 動作確認用エンドポイント `/api/health/cv` 追加
- [x] CourtAdapter / IdentityGraph / RTMPose / SwingDetector / HitterAttribution の連鎖が
      forward-compat hook で接続可能

## Out of scope (次フェーズ)

- バッチパイプライン (`routers/yolo.py`) への live wiring
- RTMPose 重みの prod 配備 (人手作業)
- Doubles 4 人同時 occlusion パターンの個別チューニング
- Track B (ConfidenceCalibrator / Platt scaling) — Phase A の override 履歴蓄積待ち
