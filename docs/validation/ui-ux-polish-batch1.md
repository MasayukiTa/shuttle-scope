# UI/UX 細部改善 バッチ1

## 実装日
2026-04-13

## 対象ファイル

| ファイル | 変更内容 |
|---|---|
| `src/components/video/VideoPlayer.tsx` | シークバーホバー時 mm:ss フローティングツールチップ |
| `src/components/common/DateRangeSlider.tsx` | つまみドラッグ中に日付フローティング表示 |
| `src/pages/SettingsPage.tsx` | スティッキーヘッダー・/キーフォーカス・localStorage永続化・名前コピー・Esc・インライン削除確認 |
| `src/pages/MatchListPage.tsx` | カラムソート・日付プリセット・一括選択+エクスポート・インライン削除確認・Esc |
| `src/pages/AnnotatorPage.tsx` | ?キーでショートカット凡例・赤on赤ボタン全箇所に border-white/60 追加 |

## 各変更の詳細

### VideoPlayer.tsx
- `seekHover` state追加（`x: number, pct: number`）
- シークバー div に `onMouseMove` / `onMouseLeave` を追加
- ホバー中はバー真上に `bg-gray-800 text-white` のツールチップを表示
- `formatTime()` で mm:ss 変換（既存関数を流用）

### DateRangeSlider.tsx
- `activeHandle: 'a'|'b'|null` state追加
- `makeDragHandler` の `pointerdown` で `setActiveHandle`、`pointerup` で `null` に戻す
- アクティブなつまみの上部にインラインスタイルでツールチップ表示
  - ライト: `background #1e293b` / ダーク: `background #374151` / 文字 `#ffffff`

### SettingsPage.tsx
- **スティッキーヘッダー**: `<thead className="sticky top-0 z-10 {bodyBg}">` — bodyBg でモード別背景を確保
- **`/` キー**: `useEffect` + `keydown` で選手タブ時のみ検索バーにフォーカス
- **localStorage永続化**: `playerSortKey` / `playerSortDir` の初期値を localStorage から取得、`handlePlayerSort` 内で書き込み
- **名前コピー**: 名前セルを `<button>` に変更、ホバーで薄く「コピー」表示、クリック後1.5秒 `bg-green-500 text-white border border-white` バッジ
- **Esc**: `showPlayerForm` が true の間だけリスナーを登録
- **インライン削除確認**: `deleteConfirmId` state、ゴミ箱ボタン押下で行内に「削除｜取消」を表示、色は `bg-red-50/bg-red-900/30` + `text-red-700/text-red-400` + `border border-white`

### MatchListPage.tsx
- **カラムソート**: `matchSortKey` / `matchSortDir` state、`useMemo` でフィルタ後にソート。日付/大会名/結果が対象。日付は初期降順
- **日付プリセット**: 直近1週・直近1ヶ月・直近3ヶ月のボタン。既存のフィルタ state（`filterDateFrom`/`filterDateTo`）を更新するだけ
- **一括選択**: `selectedMatchIds: Set<number>`、デスクトップテーブルの先頭列にチェックボックス追加、選択時に青い一括操作バーが浮上、`/api/sync/export/match?match_ids=...` にリンク
- **インライン削除確認**: SettingsPage と同一パターン
- **Esc**: `showForm` が true の間だけリスナーを登録

### AnnotatorPage.tsx
- **`?` キー**: `useEffect` で `keydown` を監視、`showLegendOverlay` をトグル
- **凡例モーダル**: 表示条件を `isMatchDayMode && showLegendOverlay` → `showLegendOverlay` に緩和
- **赤on赤修正**: 以下3箇所に `border border-white/60` を追加
  - ラリーキャンセルボタン（`bg-red-900/50 text-red-400`）
  - TrackNet エラーリトライボタン
  - YOLO エラーボタン

## 動作確認チェックリスト

- [ ] VideoPlayer: シークバーをホバーすると時刻ツールチップが出る
- [ ] DateRangeSlider: ドラッグ中だけ日付ツールチップが出て、離したら消える
- [ ] 選手リスト: スクロールしてもヘッダーが固定される
- [ ] 選手リスト: `/` キーで検索バーにフォーカスが当たる
- [ ] 選手リスト: ソート状態がページ離脱後も復元される（localStorage）
- [ ] 選手リスト: 名前クリックで「コピー済」バッジが出て1.5秒後に消える
- [ ] 選手フォーム: Esc で閉じる
- [ ] 選手リスト: ゴミ箱ボタンでインライン確認が出て削除/取消できる
- [ ] 試合一覧: 日付/大会名/結果ヘッダーがクリックでソートされる
- [ ] 試合一覧: 日付プリセットボタンでフィルタが適用される
- [ ] 試合一覧: チェックボックスで複数選択、青バーからエクスポートできる
- [ ] 試合一覧: ゴミ箱でインライン確認が出る
- [ ] 試合フォーム: Esc で閉じる
- [ ] アノテーター: `?` キーでショートカット凡例が開閉する
- [ ] アノテーター: ラリーキャンセルボタンに白ボーダーが付いて視認性が上がる
- [ ] ビルドエラーなし ✅
