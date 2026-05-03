# Mobile UI Responsive Pass — 2026-05-04

## Scope
ユーザ報告「モバイル向けUIが全体的に結構崩壊している」を受けて、優先度の高い 5 ページを横断修正。
ボタンの処理中表示 (UX) も併せて追加。

## Changes

### ConditionPage
- `grid-cols-1 lg:grid-cols-2` → `grid-cols-1 md:grid-cols-2` (4 箇所)
- タブレット縦持ちで 1 列のまま無駄に縦長になっていたのを解消。

### TeamManagementPage
- 既存の生 `<table>` を `useIsMobile` フックで mobile (<768px) 時はカードリストに切替。
- カードでは表示名/識別子/種別バッジ/メンバー展開ボタン/編集ボタンを縦積み。
- "新規作成" ボタンに作成中スピナー (`Loader2`) と disabled 化。
- 編集行の保存ボタンに `savingId === t.id` のスピナー表示。
- ヘッダボタン: モバイルでは "追加"、デスクトップでは "新規作成" の文言切替。
- 作成モーダル: ボタンを `flex-col-reverse sm:flex-row` でモバイル時は縦積み + 全幅。

### SettingsPage (2880 行)
- `grid-cols-1 lg:grid-cols-2` → `md:grid-cols-2` (3 箇所)
- ルート padding を `p-6` → `p-3 sm:p-6`。
- "暫定プレイヤー" テーブルに `overflow-x-auto` ラッパ + `min-w-[480px]` を付与。
- モバイル時は "プロフィール状態" "利き腕" カラムを `hidden sm:table-cell` で非表示化（重要カラムを優先）。

### CameraSenderPage
- もともと `max-w-sm` 単一カラムで mobile-first 設計だったため、レイアウト変更は不要。
- 参加ボタン: `senderState === 'connecting'` 時にスピナー + "接続中…" 表示 + disabled。
- カメラ起動ボタン: `startingCamera` ローカル state を追加してスピナー + "起動中…" + disabled。

### ExpertLabelerAnnotatePage
- `grid-cols-1 lg:grid-cols-2` → `md:grid-cols-2` (1 箇所)
- ルート padding は既に `p-3 md:p-5` で対応済。

## Pattern Notes (横展開時の参考)
- table → card 切替は `useIsMobile()` フックで判定（768px breakpoint）
- 横持ち維持テーブルは `<div className="overflow-x-auto">` + `min-w-[N]` でラップ
- モバイル不要カラムは `hidden sm:table-cell`
- ボタンは fetch 中 `disabled={loading}` + `<Loader2 className="animate-spin" />` を併記し、文言を "処理中…" 系に切替

## Validation
- `npm run build` 成功（2883 modules transformed, 12.72s）
- 既存の レスポンシブUI制約 (CLAUDE.md) は全て遵守:
  - input/select font-size 16px は globals.css 維持
  - タブの `overflow-x-auto scrollbar-hide` 維持
  - MatchListPage の card/table 切替パターンを TeamManagementPage に踏襲

## Out of Scope (今回未対応)
- AnnotatorPage (4418 行): 既に 37 個の responsive class があり相対的に健全
- UserManagementPage / NotificationInboxPage: 既に `hidden sm:table-cell` 等あり
- AdminBillingPage / AuditLogPage: 管理者用、モバイル優先度低
