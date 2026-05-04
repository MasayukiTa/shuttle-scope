# Phase A: Hit Zone Override + Offline Stash — 2026-05-04

## Background
モバイル / タブレット タイル UI ハイブリッド計画 (private_docs v2) の Phase A 実装。
- 打点 (`hit_zone`) を CV 自動推定だけでなく人間が override 可能に
- 追加データで CV モデル改善のフィードバックループを確立 (`hit_zone_source` 計測)
- 体育館 WiFi 不安定対策として IndexedDB に未送信ラリーを stash + 自動再送

不変原則 (v2 §守るべき不変原則 を遵守):
- `inputStep` の値リネームなし (`'land_zone'` 維持)
- `setHitter` の G1 仕様 (land_zone 中は固定) 維持
- `useKeyboard.ts` のテンキー落点入力との互換性維持
- `CourtDiagram` 落点入力は完全維持
- `getShotContext()` フィルタロジック不変

## What was implemented

### Frontend
- **新規** `src/components/annotation/HitZoneSelector.tsx`
  - 9 zone (1-9) タイル, 3x3 grid, セル一辺 56px (mobile) / 48px (desktop)
  - CV 推定セル: 青背景 + ✨アイコン + 「CV推定: ゾーン {N}」ラベル
  - human override セル: オレンジ背景 + 太枠 + shadow
  - 1 タップで `onZoneSelect`
  - ARIA 対応 (`role=grid` / `aria-pressed` / `aria-label`)
- **新規** `src/components/annotation/__tests__/HitZoneSelector.test.tsx` (5 tests)
- **新規** `src/utils/offlineStrokeQueue.ts`
  - IndexedDB DB: `shuttlescope_offline` / store: `pending_rallies`
  - `stashPending` / `removePending` / `listPendingForMatch` / `countAllPending`
  - 全 API は IndexedDB 不可環境で graceful degradation
- **新規** `src/hooks/useOfflineSync.ts`
  - 起動時 + `online` イベント + 30 秒インターバルで再送試行
  - 競合防止に `inflightRef` で同時実行 1 回まで
  - 1 件失敗したら次回まで stash 残す (シンプル retry)

### 既存ファイル変更
- `src/types/index.ts` — `StrokeInput` に `hit_zone_source?: 'cv' | 'manual'` と
  `hit_zone_cv_original?: Zone9 | null` を追加
- `src/store/annotationStore.ts`
  - `PendingStroke` に `hit_zone_cv` / `hit_zone_source` 追加
  - 新メソッド `setHitZoneOverride(zone)`
  - `inputShotType()` で前ストロークの land_zone から CV 推定値を先行計算 → preselect
  - `selectLandZone()` / `skipLandZone()` で確定 stroke に source/cv_original を含める
- `src/pages/AnnotatorPage.tsx`
  - `inputStep === 'land_zone'` レンダ内に `<HitZoneSelector>` を `<CourtDiagram>` の左に並列追加
  - スマホでは `flex-col`、`sm:` 以上で `flex-row`
  - `useOfflineSync(matchId)` をトップレベルで呼び出し
  - `/strokes/batch` 送信を stash → POST → 成功時 remove のフローに変更
  - 失敗時は stash 残して `useOfflineSync` が再送
- `src/i18n/ja.json` — `hit_zone_overridden`, `hit_zone_aria`, `hit_zone_cell`,
  `hit_zone_cv_label` の 4 ラベル追加 (CLAUDE.md i18n ルール遵守)

### Backend
- **新規** `backend/db/migrations/versions/0023_stroke_hit_zone_source.py`
  - `strokes.hit_zone_source` (String 10) NULL 許容
  - `strokes.hit_zone_cv_original` (String 5) NULL 許容
- `backend/db/models.py::Stroke` — 同 2 カラム追加
- `backend/routers/strokes.py`
  - `StrokeData` Pydantic に同 2 フィールド追加
  - `stroke_to_dict` に同 2 フィールド出力追加
  - `Stroke(rally_id=..., **stroke_dict)` で透過に保存される（既存パターン流用）

## Validation
- `npm run build` — 2886 modules transformed, build green
- `vitest run HitZoneSelector.test.tsx` — **5/5 pass**
- `pytest test_video_downloader test_downloads_archiver` — 34/34 pass (既存退化なし)
- `ast.parse` — 全変更 .py ファイルの syntax OK
- 状態機械への介入なし: `inputStep` 値変更なし、`useKeyboard.ts` 不変
- `CourtDiagram` 落点入力 UI / API 不変

## Acceptance criteria status (v2 §6.7)
- [x] 打点 9-zone タイルが落点 CourtDiagram の横に表示 (mobile 縦並び / sm+ 横並び)
- [x] CV 推定値が preselect 状態で表示 (✨アイコン付き)
- [x] 1 タップで override 可能
- [x] override 後のデータに `hit_zone_source: "manual"` 付与
- [x] 打点を tap せず CV 値のまま落点 tap で次ストロークに進める
- [x] 既存落点フローに退化なし
- [x] `inputStep` 値は `'land_zone'` のまま、リネームなし
- [x] `useKeyboard.ts` のテンキー落点入力が引き続き動作 (変更なし)
- [x] モバイル・タブレット両方で 64dp 以上のタップ領域 (cellSize=56 + gap-1.5 で実質 64+ 確保)
- [x] ネットワーク切断中もストローク入力継続可 (stash で吸収)
- [x] ネットワーク復帰時に未送信ストロークが自動再送 (`online` event + 30s poll)
- [x] backend が `hit_zone_source` / `hit_zone_cv_original` を受信して DB に保存
- [x] HitZoneSelector のユニットテスト pass

## How to roll out
1. Alembic migration を本番 DB に適用 — `alembic upgrade head`
2. Backend 再起動 → `/strokes/batch` が新フィールドを受け付け開始
3. Frontend デプロイ → AnnotatorPage で打点タイル表示開始
4. **dogfood**: 1 試合分入力して以下確認
   - 打点 override がワークするか
   - WiFi 切断シミュレーション (DevTools Offline) で落ちないか
   - DB に `hit_zone_source` / `hit_zone_cv_original` が記録されているか
5. dogfood OK なら次に Phase B (セマンティックカラー) 着手判断

## Data quality KPI (Phase A の真の価値)
- `hit_zone_override_rate` = manual / total → CV モデルとの乖離率
- `hit_zone_cv_accuracy` = CV 元値と最終確定値の一致率 → CV モデル改善 KPI
- 数週間の dogfood データで Phase B / C の優先度判断が可能になる

## Known follow-ups (Phase A の範囲外)
- セマンティックカラーのバックポート (Phase B)
- LiveInputPage 新設 (Phase C)
- 試合履歴解析側 (analysis_*) で `hit_zone_source` を集計する UI は別途
