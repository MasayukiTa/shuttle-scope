# ShuttleScope No-Video Execution Plan 10H — 実装完了記録

## 日付
2026-04-10

## ステータス
**全優先タスク実装完了（Priority 1〜6）。ビルド ✓（3014 modules, no errors）。バックエンドテスト 28/28 PASSED。フロントエンドテスト 50/50 PASSED。**

---

## 実施計画

対応仕様: `private_docs/ShuttleScope_NO_VIDEO_EXECUTION_PLAN_10H_v1.md`

実装は2セッションにまたがる:
- **前セッション** (`2026-04-10_remote_cv_tunnel_completion_report.md`): Priority 2A/2B・Priority 3・Priority 4の主要部分
- **本セッション**: Priority 1（CV補助UX強化）・Priority 2C（apply監査）・Priority 5（ワーディング）・Priority 6（テスト・バリデーション）

---

## Priority 1: CV補助アノテーションワークフロー強化（本セッション）

### A. CVAssistPanel 強化 ✓

**変更ファイル**: `src/components/annotation/CVAssistPanel.tsx`（全面改修）

実装内容:
- `CVFieldChip` サブコンポーネント: 値・バッジ・信頼度 %（エメラルド≥72% / 青≥48% / アンバー<48%）・ソースラベル（TN/YOLO/ALN/FUS）・承認ボタン（suggested のみ）
- `StrokeRow`: ChevronRight/Down で展開可能な理由コード表示（`track_present_high_confidence` は非表示）
- ラリーレベルの要確認理由をカテゴリ別に分類（データ: low_frame_coverage / alignment_missing、品質: その他）
- サマリーバーの着地ゾーン・打者フィルレートを信頼度ティアで色分け
- ダブルスロール安定度を色分け（emerald if ≥0.65）

### B. 細粒度適用コントロール ✓

**変更ファイル**:
- `src/pages/AnnotatorPage.tsx` — 適用コントロール群の追加
- `src/hooks/annotator/useCVCandidates.ts` — `applyCandidates(mode, fields)` 引数追加・applyResult 型拡張
- `backend/routers/cv_candidates.py` — apply エンドポイントのフィールドレベル監査

実装した適用ボタン:
| ボタン | mode | fields | 用途 |
|--------|------|--------|------|
| 高確信度適用 | auto_filled | land_zone + hitter | メイン適用（安全） |
| 着地のみ | auto_filled | land_zone | 打者不明なときに使う |
| 打者のみ | auto_filled | hitter | 着地は手動入力したいとき |
| 候補も含む | suggested | land_zone + hitter | 中確信度まで承認するとき |

適用結果フィードバック（件数 + フィールド内訳）を表示。
apply 中は全ボタンを `disabled`（`cvBuildLoading || cvApplyLoading`）。

### C. バックエンド apply エンドポイント強化 ✓

**変更ファイル**: `backend/routers/cv_candidates.py`

`POST /api/cv-candidates/apply/{match_id}` レスポンスに追加:
```json
{
  "updated_strokes": int,
  "land_zone_count": int,
  "hitter_count": int,
  "applied_by_mode": "auto_filled"|"suggested"|"all",
  "applied_fields": ["land_zone", "hitter"]
}
```
サイレントミューテーションなし: 値が同じ場合は変更しない（`if stroke.land_zone != lz["value"]`）。

### D. レビューキュー改善 ✓

**変更ファイル**: `src/components/annotation/ReviewQueuePanel.tsx`（全面改修）

実装内容:
- ラリーごとに `CVCandidatesData` から信頼度サマリー（着地・打者フィルレート）を表示（`ConfidencePill` コンポーネント）
- 理由コードをカテゴリ別に分類（データ / 品質 / その他）+ 折りたたみ
- 完了済みをトグル表示（デフォルト非表示）
- `candidatesData` prop を追加してラリー候補から信頼度を lookup
- `onJumpToRally` コールバック（jump-to-rally 準備完了、動画タイムスタンプ連携は将来拡張）

**変更ファイル**: `src/pages/AnnotatorPage.tsx`
- `CVReviewQueuePanel` に `candidatesData` prop を渡すように変更

---

## Priority 2: バックエンド候補パイプライン強化（前セッション実装済み）

**参照**: `docs/validation/2026-04-10_cv_assisted_auto_annotation_implementation.md`

### A. Candidate builder cleanup ✓（前セッション）

**実装ファイル**: `backend/cv/candidate_builder.py`

- しきい値を先頭に集約: `CONF_HIGH=0.72`, `CONF_MEDIUM=0.48`, `TRACKNET_MIN_CONF=0.38`, `HITTER_MATCH_WINDOW_SEC=0.6`, `LAND_SEARCH_WINDOW_SEC=3.0`
- decision mode マッピングを `_conf_to_decision()` に集約
- reason-code 生成を `_compute_review_reasons()` に集約
- ロジックは決定論的（テスト 28件で確認済み）

### B. 候補メタデータの永続化 ✓（前セッション）

`MatchCVArtifact` テーブルに `artifact_type='cv_candidates'` として保存。各フィールドに以下を含む:
- `value`, `confidence_score`, `source`, `decision_mode`, `reason_codes`（ストロークレベル）
- `review_reason_codes`, `cv_confidence_summary`, `built_at`（ラリーレベル）

DBマイグレーション不要（既存スキーマ活用）。

### C. Apply-path 監査 ✓（本セッション で完成）

上記 Priority 1.C を参照。`land_zone_count`, `hitter_count`, `applied_by_mode`, `applied_fields` を返す。

---

## Priority 3: トンネル/リモート UX 誠実性（前セッション実装済み）

**参照**: `docs/validation/2026-04-10_remote_cv_tunnel_completion_report.md`

### A. トンネル状態メッセージ ✓（前セッション）

**実装ファイル**: `backend/routers/tunnel.py`, `src/hooks/annotator/useSessionSharing.ts`

状態の明確な分離:
- 未起動: ボタン空白
- 起動中（URL未取得）: `取得中...` 表示 + amber スタイル
- 公開URL取得完了: `稼働中` 表示（本セッションで "ON" → "稼働中" に変更）
- 失敗: `tunnelLastError` を赤テキストで表示（タイムアウト・認証失敗など）

### B. ngrok 診断可視性 ✓（前セッション）

- stdout JSON パースによる URL 取得（`_read_stdout_ngrok` スレッド）
- タイムアウト時にプロセスを強制終了し `_proc=None` にリセット → 「取得中...」永久ハング解消
- `tunnelLastError` で認証失敗・タイムアウトをUI に表示

### C. 共有フローの防衛 ✓（前セッション）

- `tunnelPending` 中は共有モーダルを開かない（`if (tunnelPending) return`）
- LAN URL（`10.xxx.xxx.xxx`）が公開URL として表示される URL 合成バグを修正

---

## Priority 4: Annotator 構造的クリーンアップ（前セッション実装済み）

**参照**: `docs/validation/2026-04-10_cv_assisted_auto_annotation_implementation.md`

### 実施済み分解 ✓

- `useCVCandidates.ts` — CV 候補取得・ビルド・適用・レビューキューを管理するフック
- `CVAssistPanel.tsx` — ラリーCV候補パネル（プレゼンテーション）
- `ReviewQueuePanel.tsx` — レビューキューパネル（プレゼンテーション）
- `CVCandidateBadge.tsx` — decision_mode バッジ（再利用コンポーネント）

### 今回追加した内部構造 ✓

- `CVFieldChip` サブコンポーネント（CVAssistPanel 内）
- `StrokeRow` サブコンポーネント（CVAssistPanel 内）
- `ConfidencePill` サブコンポーネント（ReviewQueuePanel 内）
- `QueueItem` サブコンポーネント（ReviewQueuePanel 内）

コアアノテーション意味論・キーボードフロー・保存セマンティクスは変更なし。

---

## Priority 5: ワーディングクリーンアップ（本セッション）

### マッチデーモード → 試合中モード

**変更ファイル**: `src/pages/AnnotatorPage.tsx`（5箇所）、`src/components/annotation/ShotTypePanel.tsx`（1箇所）
- `src/i18n/ja.json` の `match_day_mode` キー自体は前セッションで修正済み
- 残っていたコメント・文字列ラベルをすべて修正

### ボタンラベル明確化

| 変更前 | 変更後 | 場所 |
|--------|--------|------|
| `詳細` | `CV詳細` | CVAssistPanel トグルボタン |
| `ON` | `稼働中` | トンネルステータスボタン |
| `MD ON` | `試合中 ●` | 試合中モードボタン（アクティブ時） |
| `自動適用`（単一ボタン） | 4種の細粒度ボタン | CV補助グループ |

---

## Priority 6: テストと検証スキャフォールディング（本セッション）

### バックエンドテスト ✓

**新規ファイル**: `backend/tests/test_candidate_builder.py`

28ケース、全件 PASSED:
- `TestConfToDecision` (6ケース) — しきい値境界・decision_mode マッピング
- `TestInferLandZone` (7ケース) — フレームフィルタ・ゾーン一貫性・ウィンドウ制限
- `TestInferHitter` (5ケース) — アライメント優先・ウィンドウ外無視・高確信度モード
- `TestComputeReviewReasons` (5ケース) — 各 reason_code の生成条件
- `TestBuildCandidates` (5ケース) — 統合テスト（モックデータ）

```
28 passed, 1 warning in 0.11s
```

### フロントエンドテスト ✓

**新規ファイル**: 50ケース、全件 PASSED

| ファイル | ケース数 | 内容 |
|---------|---------|------|
| `src/components/annotation/__tests__/CVCandidateBadge.test.tsx` | 6 | ラベルテキスト・compact サイズ |
| `src/components/annotation/__tests__/CVAssistPanel.test.tsx` | 20 | null状態・サマリー・フィールド表示・✓ボタン・理由展開・ダブルスロール |
| `src/components/annotation/__tests__/ReviewQueuePanel.test.tsx` | 15 | 空状態・完了ボタン・理由カテゴリ展開・信頼度ピル・completed トグル |
| `src/hooks/annotator/__tests__/tunnelStatusDisplay.test.tsx` | 9 | pending/稼働中/未起動・エラー表示・cursor-wait・[ngrok]プレフィックス除去 |

```
50 passed in 4.75s
```

### バリデーションテンプレート ✓

**新規ファイル**: `docs/validation/templates/`
- `real_video_cv_validation_template.md` — Phase 1-4 の定量バリデーション表
- `remote_share_validation_template.md` — トンネル状態・実機接続テスト
- `auto_annotation_acceptance_checklist.md` — 受け入れ基準チェックリスト（合格基準数値入り）

---

## Concrete Implementation Checklist（実施計画より）

### Candidate UX
- [x] CVAssistPanel shows field-by-field structure
- [x] CVCandidateBadge clearly maps decision modes
- [x] candidate confidence is visible
- [x] source is visible
- [x] reason codes are visible or expandable

### Apply controls
- [x] apply only auto-filled（高確信度適用）
- [x] apply only suggested（候補も含む）
- [x] apply only land_zone（着地のみ）
- [x] apply only hitter（打者のみ）
- [x] show updated count（N件適用 + 着地N件 / 打者N件）
- [x] avoid duplicate apply confusion（4 distinct buttons, disabled during apply）

### Review queue
- [x] pending/completed split
- [x] clearer reason labels（カテゴリ別）
- [x] confidence shown（ConfidencePill per rally）
- [x] jump-ready structure（onJumpToRally callback 実装済み、動画タイムスタンプ連携は将来拡張）

### Tunnel UX
- [x] pending state visible（取得中...）
- [x] error visible（tunnelLastError 赤テキスト）
- [x] not falsely "ready"（LAN URL バグ修正済み）
- [x] remote share blocked until truly ready（if (tunnelPending) return）

### Naming
- [x] all remaining マッチデー wording replaced（全6箇所）
- [x] 試合中モード consistently used

### Tests
- [x] backend candidate tests expanded（28ケース）
- [x] frontend CV assist tests added（CVCandidateBadge 6 / CVAssistPanel 20 / ReviewQueuePanel 15 ケース）
- [x] tunnel status rendering tested（tunnelStatusDisplay 9 ケース）

---

## ビルド結果

```
✓ 3014 modules transformed.
✓ built in 7.20s（No errors）
```

---

## テスト結果

```
バックエンド: 28 passed, 1 warning in 0.11s
フロントエンド: 50 passed in 4.75s
合計: 78 passed
```

---

## 変更ファイル一覧（本セッション）

### フロントエンド

| ファイル | 変更内容 |
|---------|---------|
| `src/components/annotation/CVAssistPanel.tsx` | 全面改修: CVFieldChip, 信頼度 %, ソースラベル, 理由コード展開 |
| `src/components/annotation/ReviewQueuePanel.tsx` | 全面改修: 信頼度表示, 理由カテゴリ分類, 完了トグル, candidatesData prop |
| `src/hooks/annotator/useCVCandidates.ts` | applyResult 型拡張, applyCandidates(mode, fields) 引数追加, applyLoading 追加 |
| `src/pages/AnnotatorPage.tsx` | 4ボタン適用コントロール, 結果フィードバック強化, candidatesData prop 渡し, ワーディング修正 |
| `src/components/annotation/ShotTypePanel.tsx` | コメントのワーディング修正（試合中モード） |

### バックエンド

| ファイル | 変更内容 |
|---------|---------|
| `backend/routers/cv_candidates.py` | apply レスポンスにフィールドレベル監査 (land_zone_count, hitter_count, applied_by_mode, applied_fields) 追加 |

### テスト

| ファイル | 内容 |
|---------|------|
| `backend/tests/test_candidate_builder.py` | 28ケース、candidate_builder 純粋関数テスト |
| `src/components/annotation/__tests__/CVCandidateBadge.test.tsx` | 6ケース、バッジラベル・サイズ |
| `src/components/annotation/__tests__/CVAssistPanel.test.tsx` | 20ケース、全表示条件 |
| `src/components/annotation/__tests__/ReviewQueuePanel.test.tsx` | 15ケース、キュー挙動全般 |
| `src/hooks/annotator/__tests__/tunnelStatusDisplay.test.tsx` | 9ケース、トンネル状態表示条件 |

### バリデーションテンプレート

| ファイル | 内容 |
|---------|------|
| `docs/validation/templates/real_video_cv_validation_template.md` | 実動画 CV バリデーション用 |
| `docs/validation/templates/remote_share_validation_template.md` | リモート共有実機テスト用 |
| `docs/validation/templates/auto_annotation_acceptance_checklist.md` | 受け入れ判定チェックリスト |

---

## 実環境バリデーション（要別途実施）

| 項目 | 条件 |
|-----|------|
| 着地ゾーン auto_filled 正解率 >= 80% | 実動画 + TrackNet完了 |
| 打者推定 auto_filled 正解率 >= 75% | 実動画 + YOLO完了 |
| 細粒度適用（着地/打者/候補）の動作確認 | 実動画バリデーション時 |
| レビューキュー信頼度表示の確認 | candidatesData 生成後 |
| トンネル「稼働中」・エラー表示の確認 | ngrok 実行時 |
| 共有モーダルブロック（tunnelPending）の確認 | 実機テスト時 |

---

## 次フェーズ持ち越し

| 項目 | 優先度 |
|-----|--------|
| jump-to-rally 動画タイムスタンプ連携 | 低（実環境データ後） |

---

## 関連ドキュメント

- `private_docs/ShuttleScope_NO_VIDEO_EXECUTION_PLAN_10H_v1.md` — 実施計画
- `docs/validation/2026-04-10_cv_assisted_auto_annotation_implementation.md` — CV補助実装（前セッション）
- `docs/validation/2026-04-10_remote_cv_tunnel_completion_report.md` — トンネル修正（前セッション）
- `docs/validation/templates/` — 実動画バリデーションテンプレート群
