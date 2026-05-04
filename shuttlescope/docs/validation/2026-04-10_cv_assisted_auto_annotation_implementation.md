# CV補助自動アノテーション実装完了記録

## 日付
2026-04-10

## ステータス
**全フェーズ実装完了。ビルド ✓（3014 modules, no errors）。Python import ✓。**
実環境バリデーション（実動画 + CV解析完了後）は別途必要。

---

## 実装概要

仕様: `private_docs/ShuttleScope_CV_ASSISTED_AUTO_ANNOTATION_SPEC_v1.md`

### 達成した状態変化

| Before | After |
|--------|-------|
| CV解析が完了してもオペレーターが全フィールドを手動入力 | TrackNet + YOLO 解析後に候補生成→高確信度は自動入力、中確信度は候補表示、低確信度は要確認ルーティング |
| エラー・不確実性が不可視 | 理由コード付きで要確認ラリーを自動リストアップ |
| マッチデーモード表記 | 試合中モード（前フェーズ実装済み） |

---

## Phase 1: 着地ゾーン自動入力 ✓

**実装ファイル**: `backend/cv/candidate_builder.py` — `_infer_land_zone()`

**ロジック**:
1. ストローク timestamp_sec から最大 3.0 秒後までの TrackNet フレームを取得
2. confidence >= 0.38 のフレームに絞り込み
3. ウィンドウ後半 40% のフレームでゾーン一貫性を計算（シャトル落下直前が最も安定）
4. 信頼度 = TrackNet confidence 平均 × ゾーン一貫性率
5. しきい値判定:
   - >= 0.72 → `auto_filled`（自動入力バッジ）
   - 0.48〜0.72 → `suggested`（候補バッジ）
   - < 0.48 または一貫性 < 40% → `review_required`（要確認バッジ）

---

## Phase 2: 打者候補自動推定 ✓

**実装ファイル**: `backend/cv/candidate_builder.py` — `_infer_hitter()`

**ロジック（優先度順）**:
1. **アライメントデータ優先**: `cv_alignment` アーティファクトの `hitter_candidate` + `hitter_confidence` を使用（±0.6秒ウィンドウ内の最近傍イベント）
2. **フォールバック**: YOLO + TrackNet 直接推定 — シャトル位置に最近傍のプレイヤーラベル、距離から信頼度算出（線形減衰）
3. `multiple_near_players` 理由コードで競合候補を記録

---

## Phase 3: ダブルスロール状態推定 ✓

**実装ファイル**: `backend/cv/candidate_builder.py`
- `_infer_front_back_role()` — ストロークレベル（近傍フレームの Y 位置）
- `_infer_rally_front_back_role()` — ラリーレベル（全フレームの役割安定性）

**閾値**:
- Y < 0.42 → front（ネット寄り）
- Y > 0.60 → back（バック側）
- 65%以上のフレームで同じ役割 → 安定と判定

---

## Phase 4: 自動レビューキュー ✓

**理由コード（仕様書の全コードを網羅）**:
- `low_frame_coverage` — TrackNet フレーム数 < 5
- `alignment_missing` — アライメントデータなし
- `landing_zone_ambiguous` — 過半数のストロークで landing zone が review_required
- `hitter_undetected` — 60%以上のストロークで打者不明
- `multiple_near_players` — 打者候補が競合（_infer_hitter のフォールバック経路）
- `role_state_unstable` — ダブルスロール安定度 < 0.5（fb_role.stability で判定）
- `track_present_high_confidence` — 高確信度トラック（各フィールドの reason_codes に付与）

**エンドポイント**:
- `GET /api/cv-candidates/review-queue/{match_id}` — 手動フラグ（review_status=pending）+ CV自動フラグを統合して返す

---

## Phase 5: 近自動フロー ✓

**UI フロー**:
1. TrackNet または YOLO バッチ完了 → ヘッダーに「CV補助」グループ表示
2. 「候補生成」ボタン → `POST /api/cv-candidates/build/{match_id}` → アーティファクト保存
3. 「自動適用」ボタン → `POST /api/cv-candidates/apply/{match_id}` → auto_filled のみ一括書き戻し
4. 「詳細」ボタン → 右パネルに `CVAssistPanel` 表示（各ストロークの候補をリスト表示）
5. ⚠ボタン → `CVReviewQueuePanel` 展開、要確認ラリーを一覧表示・完了マーク機能付き

**UI Requirement C（Side-by-side evidence）対応状況**:
仕様書は「シャトル軌跡・プレイヤー位置・推定打者/着地ゾーンを並べて表示」を要求。
現実装では以下で対応:
- 既存の `ShuttleTrackOverlay`（シャトル軌跡）と `PlayerPositionOverlay`（YOLO検出）が動画左パネルにオーバーレイ表示（以前のフェーズで実装済み）
- 新しい `CVAssistPanel` が右パネルに候補テキストを表示
- 両者は同じ画面に同時表示可能 → 動画オーバーレイ + テキスト候補の「実質的な side-by-side」
- 単一パネルへの統合表示（専用の evidence モーダル等）は実装しておらず、実環境でオペレーターから要望があれば Phase 5+ 拡張として対応

---

## 新規ファイル一覧

### バックエンド

| ファイル | 役割 |
|---------|------|
| `backend/cv/__init__.py` | パッケージ定義 |
| `backend/cv/candidate_builder.py` | 着地ゾーン・打者・ロール候補生成エンジン（590行） |
| `backend/routers/cv_candidates.py` | REST API（build/get/apply/review/review-queue） |

### フロントエンド

| ファイル | 役割 |
|---------|------|
| `src/types/cv.ts` | TypeScript型定義（CVDecisionMode, StrokeCVCandidate, RallyCVCandidate等） |
| `src/hooks/annotator/useCVCandidates.ts` | 候補取得・ビルド・適用・レビューキューフック |
| `src/components/annotation/CVCandidateBadge.tsx` | 自動入力/候補/要確認バッジ |
| `src/components/annotation/CVAssistPanel.tsx` | ラリーごとのCV候補パネル（ストロークリスト・ダブルスロール・理由表示） |
| `src/components/annotation/ReviewQueuePanel.tsx` | 要確認ラリーキューパネル |

### 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `backend/main.py` | `cv_candidates` ルーター登録 |
| `src/pages/AnnotatorPage.tsx` | useCVCandidates フック統合、CV補助ボタングループ、CVAssistPanel、CVReviewQueuePanel |
| `src/i18n/ja.json` | `cv_assist.*` キー群追加 |

---

## REST API 仕様

```
POST /api/cv-candidates/build/{match_id}
  → TrackNet + YOLO アーティファクトから候補を生成・保存
  → アライメントデータがなければ即時計算（align_match）
  → Response: { match_id, rally_count, built_at }

GET /api/cv-candidates/{match_id}
  → 生成済み候補を返す（未生成の場合 data: null）

POST /api/cv-candidates/apply/{match_id}
  Body: { mode: "auto_filled"|"suggested"|"all", fields: ["land_zone","hitter"] }
  → 候補をストロークに書き戻す（source_method="assisted"）
  → Response: { updated_strokes: int }

PUT /api/cv-candidates/review/{rally_id}
  Body: { review_status: "pending"|"completed" }
  → ラリーのレビューステータスを更新

GET /api/cv-candidates/review-queue/{match_id}
  → 要確認ラリー一覧（手動フラグ + CV自動フラグ統合）
```

---

## データモデル（追加なし）

既存の `MatchCVArtifact` テーブルに `artifact_type='cv_candidates'` として JSON 保存。
DBマイグレーション不要（既存スキーマを活用）。

---

## 信頼度ポリシー（spec準拠）

| Tier | しきい値 | decision_mode | UI表示 |
|------|---------|---------------|--------|
| high | >= 0.72 | `auto_filled` | 緑「自動入力」バッジ |
| medium | 0.48〜0.72 | `suggested` | 青「候補」バッジ + ✓ 承認ボタン |
| low | < 0.48 | `review_required` | 黄「要確認」バッジ |

---

## ビルド結果

```
✓ 3014 modules transformed.
✓ built in 6.37s
Python import: OK
```

---

## 実環境バリデーション（要別途実施）

| 項目 | 条件 |
|-----|------|
| TrackNet完了後の着地ゾーン自動入力 | TrackNetバッチ完了 + 実動画 |
| YOLO完了後の打者候補推定 | YOLOバッチ完了 + 実動画 |
| ダブルス前後ロール判定精度 | YOLO + ダブルス試合動画 |
| 自動適用後のstroke.source_method='assisted' | DB確認 |
| レビューキューの自動フラグ品質 | 多数ラリーでの確認 |

---

## 関連ドキュメント

- `private_docs/ShuttleScope_CV_ASSISTED_AUTO_ANNOTATION_SPEC_v1.md` — 仕様書
- `docs/validation/2026-04-10_remote_cv_tunnel_completion_report.md` — 前フェーズ完了報告
