# i18n Migration B2a: SettingsPage (2026-04-23)

## 対象
`src/pages/SettingsPage.tsx` 内のハードコード日本語のうち、孤立した単純テキスト（見出し・ボタン・テーブル列・オプション）を優先抽出し `src/i18n/ja.json` の `settings.ui.*` に集約。

## 進め方
52 件全てを一括置換するのはリスク（本番 UI 検証不可）が高いため B2a / B2b に分割。本バッチ B2a は約 35 箇所を安全に置換。残りの補間文字列・条件分岐付き文字列・動的ラベルは B2b で対応。

## 追加 i18n key（settings.ui）
`player_list`, `add_player`, `hand`, `target`, `operation`, `no_players`, `no_match_players`, `name`, `dominant_hand`, `match_count`, `tentative`, `model_state`, `backend_connecting`, `load_failed`, `package_missing`, `redetect`, `sync_settings`, `export`, `import`, `backup`, `backup_now`, `backup_running`, `saved_backups`, `cloud_packages`, `no_packages`, `fetch_in`, `conflict_review`, `keep_local`, `overwrite_with_import`, `json_package_import`, `reimport_overwrite`, `db_maintenance`, `db_size`, `wal_size`, `free_pages`, `theme`, `theme_hint`, `dark`, `light`, `restart_app`, `restart_app_btn`, `right_handed`, `left_handed`, `backend_console`, `hide`, `show`, `clear`, `importing`, `import_run`, `import_complete`

## 置換済み箇所（抜粋）
- 選手管理タブ: 選手一覧 / 選手追加 / 手 / 対象 / 操作 / 空状態 2 件
- 要レビュータブ: 名前 / 利き手 / 試合数 / 操作 / 暫定
- TrackNet/YOLO: モデル状態 / バックエンド接続中... / ロード失敗 / パッケージ未導入 / 再検出
- データ管理: 同期設定 / エクスポート / インポート / バックアップ / 今すぐバックアップ / 保存済みバックアップ / 同期フォルダ内パッケージ / パッケージファイルがありません / 取込 / 競合レビュー / ローカルを維持 / 取込データで上書き / JSON パッケージ インポート / 上書きで再インポート / インポート中... / インポート
- DB: DB メンテナンス / DB サイズ / WAL サイズ / 空きページ
- アカウント: テーマ / ライト / ダーク / アプリ再起動 / アプリを再起動 / 右利き / 左利き
- バックエンドコンソール: バックエンドコンソール / 表示 / 非表示 / クリア（`useTranslation` 追加）

## 残り（B2b で対応予定）
- 補間を含むもの（例: `エクスポート試合を...`、`追加 {n} / 更新 {m}` など）
- 配列リテラルの label（診断結果マップ、タブ key/label ペア等）
- コンパウンド JSX（`<code>` を含む説明文、色付き span）
- 色凡例系テキスト

## 検証
- `npm run build` (NODE_OPTIONS=--max-old-space-size=16384) → success (8.34s / 2861 modules)
- UI 目視は本番環境側で別途確認（ローカル検証不可）

## 次バッチ
B2b: SettingsPage 残り ~15-20 箇所 → B3: MatchListPage.tsx (30 箇所)
