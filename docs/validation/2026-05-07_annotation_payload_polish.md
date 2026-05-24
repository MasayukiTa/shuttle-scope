# 2026-05-07 アノテーション保存ペイロードの構造化と打点 override 履歴表示

## 背景

`shuttlescope/src/hooks/useAnnotation.ts` が live save 経路から外れて完全な dead code 化していた。
内容も古く、Phase A の `hit_zone_source` / `hit_zone_cv_original` と
G2 移動系 (`return_quality` / `contact_height` / `contact_zone` /
`movement_burden` / `movement_direction`) を payload から落とす不完全な形のまま残っていた。
誰かが import すると静かにデータが欠ける罠だった。

実際の保存は `AnnotatorPage.tsx` 内 `handleConfirmRally` (530〜565 行付近) が直接構築しており、
そちらは全フィールドを正しく送信していたが、

- payload 構造が約 35 行のインラインオブジェクトとして埋まっており
- フィールドが新規追加されてもそれを担保するユニットテストが存在しなかった
- StrokeHistory が `hit_zone_source === 'manual'` を視覚的に表示していなかった

ため、ユーザは「手動 override したかどうか」を履歴で確認できないし、
将来また落としても気付けない。

## 変更内容

### 1. 死んだ `useAnnotation.ts` の削除
- 完全に未参照だったことを `grep` で確認 (`useAnnotation` のみ定義箇所だけ hit)
- そのまま削除。後方互換ラッパーは残さない

### 2. 保存ペイロード構築の純関数化
- 新規: `shuttlescope/src/utils/annotationPayload.ts`
  - `buildBatchPayload(args)` を export
  - rally / strokes 全フィールドの型を明示
- `AnnotatorPage.tsx` の `handleConfirmRally` を `buildBatchPayload(...)` 1 回呼びに変更
- 入力: `setId / rallyNum / winner / endType / strokes / scoreAAfter / scoreBAfter /
  rallyStartTimestamp / isBasicMode`

### 3. ペイロードの構造的回帰テスト
- 新規: `shuttlescope/src/utils/__tests__/annotationPayload.test.ts`
- カバー項目:
  - `annotation_mode` が basic → `manual_record` / detailed → `assisted_record`
  - `source_method` が basic → `manual` / detailed → `assisted`
  - Phase A: `hit_zone_source` / `hit_zone_cv_original` が override 後も保持される
  - G2 移動系 5 フィールド (`return_quality` / `contact_height` /
    `contact_zone` / `movement_burden` / `movement_direction`) が落ちない
  - basic stroke 属性 (player / shot_type / hit_zone / land_zone /
    is_backhand / is_around_head / above_net / timestamp_sec) が保持される
  - rally メタ (set_id / rally_num / winner / end_type / rally_length /
    score_a_after / score_b_after / video_timestamp_start) が保持される
  - `rally.server` は最初の stroke の player を採用、空配列なら `player_a` fallback
  - `is_deuce` は両者 ≥ 20 で true
  - `rallyStartTimestamp = null` なら `video_timestamp_start` は undefined

### 4. StrokeHistory に打点 override バッジを追加
- `hit_zone_source === 'manual'` かつ `hit_zone_cv_original` と現在の `hit_zone` が異なる場合に
  「手動打点」バッジ (オレンジ枠) を履歴行に表示
- ホバーで `CV={CV値} → 手動={選択値}` を tooltip 表示
- i18n キー追加: `annotator.hit_zone_manual_badge` / `annotator.hit_zone_manual_tooltip` (ja/en)

## 影響範囲

- バックエンドへの送信フィールドは **変更なし**。本番 DB スキーマ非影響。
- `handleConfirmRally` のクロージャ依存配列は既存のまま (`isBasicMode` を含む既存挙動を維持)
- `StrokeHistory` の引数は不変。新規 prop 追加なし
- 本番に対する SSH 操作・DB 操作は一切なし (試験環境のリポジトリ内編集のみ)

## 検証

- 単体テスト: `shuttlescope/src/utils/__tests__/annotationPayload.test.ts` 11 項目を追加
- 既存 vitest スイートを通過させる
- lint を通す
- `NODE_OPTIONS=--max-old-space-size=16384 npm run build` で frontend build が通ることを確認

## 残タスク (out of scope)

- `handleSkipRally` / `handleScoreCorrection` の skipped ラリー保存 (`is_skipped: true`,
  rally_length=0, strokes=[]) も `buildBatchPayload` の派生として整理する余地があるが、
  本件は scope を絞って「データ取りこぼし防止」と「override 視認性」に限定した。
- handleConfirmRally の `useCallback` 依存配列に `isBasicMode` が含まれていない既存問題は未対応
  (リスクは現状の確認では低いが、別 PR で正す)。

## 関連

- `shuttlescope/src/store/annotationStore.ts` (Phase A の `hit_zone_source` /
  `hit_zone_cv_original` を保持する state)
- `shuttlescope/backend/routers/strokes.py` (受口の StrokeData / RallyData)
- `shuttlescope/backend/tests/test_annotation_mode.py` (annotation_mode / source_method の
  ORM/API テスト)
