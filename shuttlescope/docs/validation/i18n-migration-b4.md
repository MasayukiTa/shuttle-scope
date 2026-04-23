# i18n Migration B4: UserManagementPage

Date: 2026-04-23

## 目的
`src/pages/UserManagementPage.tsx` 全体のハードコード日本語を `users.manage.*` キーに移行。
事前計画にあった `DashboardOverviewPage` は現状存在しないため本バッチでは対象外。

## 変更

### src/i18n/ja.json
- `users.manage.*` キー群を新規追加 (約 50 キー)
  - 画面タイトル、ヒント、権限エラー、ユーザー追加ボタン
  - 検索、並び順、ソートオプション
  - フォームラベル (ロール / 表示名 / ログインID / パスワード / チーム名 / 選手紐付け)
  - パスワード/PIN ラベル 4 種 (新規/更新 × player/その他)
  - ページアクセス UI (個人 / チーム全体(名前)補間)
  - 保存/保存中/キャンセル
  - テーブル列ヘッダー、行内 Team/Player プレフィックス、認証済み/未設定、空状態
  - 削除/リセット確認ダイアログ ({{name}} 補間)
  - パスワード表示/非表示の title & aria-label
  - role ネスト (admin / analyst / coach / player)

### src/pages/UserManagementPage.tsx
- `PAGE_ACCESS_OPTIONS` の `label` を `labelKey` に変更し JSX 側で `t(labelKey)` で解決
- `ROLE_LABELS` 定数を `ROLE_KEYS` (i18n キー map) に置換
- `SecretField` に `useTranslation` を追加しパスワード表示トグルのラベルを翻訳
- すべての JSX 内ハードコード文字列 (~25 箇所) を `{t(...)}` に置換
- 確認ダイアログ 2 種 (削除 / パスワードリセット) を `t(..., { name })` に変更

## 検証
- `NODE_OPTIONS=--max-old-space-size=16384 npm run build` 成功 (12.64s)
- 既存テスト影響なし (UI テキストのみの変更)

## 既知の制約
- `Team:` / `Player:` プレフィックスはそのまま英語リテラルで残り `:` も英語コロン。必要なら後続で調整。
- 手動 UI スモーク未実施。

## 今後
- B5: DoublesAnalysis + CourtHeatModal + analysis 上位 10
- B6: annotation 関連コンポーネント 上位 10
- B7: 残り 45+ ファイル
