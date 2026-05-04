# Track A: Person Tracking Overhaul — 2026-05-04

ベース計画: `private_docs/2026-05-04_track_a_implementation_plan.md`
スコープ: A1 〜 A5 全完了

## Summary

| # | 項目 | ファイル | テスト |
|---|---|---|---|
| A1 | ByteTrack デフォルト ON + track_id ラベル継続 | `backend/yolo/inference.py` | `test_yolo_label_continuity.py` 7/7 |
| A2 | court_calibration → candidate_builder / court_mapper 連携 | `backend/cv/court_adapter.py` (新規) + 既存 2 ファイル更新 | `test_court_adapter.py` 13/13 |
| A3 | `_track_identities` を `identity_graph.py` に抽出 | `backend/cv/identity_graph.py` (新規) + `routers/yolo.py` thin delegate | `test_identity_graph.py` 20/20 |
| A4 | OcclusionDetector + OcclusionResolver | `backend/cv/occlusion.py` (新規) | `test_occlusion.py` 12/12 |
| A5 | RallyBoundaryDetector | `backend/cv/rally_boundary.py` (新規) | `test_rally_boundary.py` 8/8 |
| **合計** | | | **60 件すべて pass** |

退化なし回帰: 既存 `test_security_invariants` / `test_video_downloader` / `test_downloads_archiver` 含めて **108 passed, 4 skipped**.

## Details

### A1: ByteTrack default ON
- `inference.py` の env デフォルトを `'0' → '1'` に変更。`SS_YOLO_BYTETRACK=0` を明示すれば従来 OFF 動作にロールバック可。
- `_assign_player_labels` を track_id 継続ロジックで強化:
  - 各 person 検出に track_id があり前フレームで同じ track_id にラベル割当があれば、そのラベルをそのまま継続
  - 未解決の検出のみ従来の信頼度 + 位置ベース割当
- `reset_tracker()` で track_id 継続マップも合わせてクリア。

### A2: court_calibration adapter
- 既存 `routers/court_calibration.py` の homography を thin adapter で公開:
  - `pixel_to_court` / `court_to_pixel` の双方向変換
  - 動的閾値 `front_threshold_y`, `back_threshold_y`, `formation_min_y_diff`, `formation_min_x_diff`
  - 高レベル `depth_band(x, y)`, `in_court(x, y)`, `formation_type(p1, p2)`
- `candidate_builder.py` の `_infer_front_back_role` / `_infer_rally_front_back_role` に `court_adapter` パラメータを追加。`build_candidates` 起点で `CourtAdapter.for_match(match_id)` を自動ロード。
- `court_mapper.py::classify_formation` に同様の `court_adapter` パラメータ追加。
- **未キャリブレーション match では fallback** (env / hard-coded) で完全互換動作。

### A3: identity_graph 抽出
- `routers/yolo.py::_track_identities` (元 ~400 行) を **ロジック完全互換** で `backend/cv/identity_graph.py::track_identities` 関数 + `IdentityGraph` クラスに抽出。
- routers 側は thin delegate に置換。`scipy.linear_sum_assignment` + 貪欲フォールバック / ByteTrack 強一致 / REID gallery / negative gallery / reacquisition 含めすべて維持。
- 純粋ヘルパー (`bbox_iou`, `cos_sim`, `cos_sim_gallery`, `foot_in_roi`) も `identity_graph.py` に併設。
- Forward-compat: `IdentityGraph.get_confidence(label)` (Track B 接続点) と `inject_pose_features(label, kp)` (Track C 接続点) を実装。

### A4: OcclusionDetector + OcclusionResolver
- 3 パターン (`PLAYER_COUNT_DROP` / `BBOX_EXPANSION` / `PRE_OCCLUSION_IOU`)。P3 が新規価値: 遮蔽が起きる**前**に検知して reid template 凍結のフックに使える。
- 4 信号 (motion / court / reid / trajectory) を weighted sum + Hungarian (scipy / 貪欲フォールバック) で 1-to-1 割当。
- `min_score` 未満の割当は drop して安全側 (False positive 抑制)。

### A5: RallyBoundaryDetector
- 3 信号 (`shuttle_missing` / `player_static` / `serve_position`) AND ベース判定。
- `min_signals` パラメータで AND 条件を緩めることが可能 (デフォルト 2)。
- `min_rally_seconds` で短すぎるラリーを ignore、`cooldown` で連続発火防止。
- ラリー境界は **suggested として CVAssistPanel で人間確認** する想定 (自動でラリーを切らない退化リスクゼロ設計)。

## Forward Compatibility Hooks

Track B / C で利用可能:
- `IdentityGraph.get_confidence(label)` → ConfidenceCalibrator (Track B)
- `IdentityGraph.inject_pose_features(label, kp)` → RTMPose / SwingDetector (Track C)
- `CourtAdapter.for_match(match_id)` → 全 CV モジュール統一の動的閾値プロバイダ

## Validation
- 新規 60 件 + 既存 regression 48 件 = **108 passed / 4 skipped**
- syntax check (ast.parse) 全変更ファイル OK
- `routers/yolo.py` の `_track_identities` シグネチャ完全互換
- 既存 `/api/cv-candidates/*` レスポンス互換 (ロジック維持)
- DB スキーマ変更なし
- 未キャリブレーション match で退化しない (フォールバック確認)

## Out of scope (Track B / C へ)

- BoT-SORT 切替 — 必要性は dogfood 後判断
- ConfidenceCalibrator (Platt scaling) — Track B (Phase A の `hit_zone_source` データ蓄積待ち)
- RTMPose / SwingDetector — Track C (5060Ti 入手待ち)
- TrackNet 本重み配備 — Track C
- Doubles 4 人同時オクルージョン専用パターン — Track C
- ラリー境界の自動 DB 反映 (現状は suggested 表示まで) — UX 確定後に追加
