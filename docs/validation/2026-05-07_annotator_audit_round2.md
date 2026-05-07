# 2026-05-07 アノテーター監査 Round 2 一括対応

ユーザ要請: 「他このような整合性の取れていないUIUXが破綻してるアノテーションの画面はあるかな」
→ 包括監査で 27 件検出 → 重大 + 重要の 10 件を全部対応。

## 修正対象

### #1 SettingsModePanel の dead button
`SettingsModePanel.tsx:122-138` の「コートキャリブレーション」「キーボード一覧」ボタンが永久 disabled だった (props 未配線)。
AnnotatorPage の 2 箇所 (デスクトップ + BottomSheet) で:
- `onOpenCalibration={() => setCourtGridVisible(true)}`
- `onOpenKeyboardLegend={() => setShowLegendOverlay(true)}`
を渡すよう修正。さらに #10 と合わせて `playerAStart` / `initialServer` 系も
プロパティ化して渡す。

### #9 モバイル戻るボタン aria-label
`{!isMobile && '戻る'}` でアイコンのみのときアクセシブル名がなかった。
`aria-label={t('annotator.ui.back')}` + `title=` を追加、`ArrowLeft` に
`aria-hidden` も付与。

### #7 AttributePanel aria 属性追加
- ルート div に `role="group"` + `aria-label`
- BH/RH ボタンに `aria-pressed` + `aria-disabled` + `aria-keyshortcuts="Q"` / `"W"`
- ネット 3 値選択に `role="radiogroup"` / 各ボタンに `role="radio"` + `aria-checked`
- ハードコード "ネット:" を `t('annotator.net_label')` に
- disabled 時の cursor / opacity を radio 側にも適用

### #8 init エラー時のリトライボタン
旧: `戻る` ボタンのみ → ページリロード必須
新: `再試行` (autoFocus) + `戻る` の 2 ボタン構成。
`再試行` は `setInitError(null)` + `initStartedRef.current = false` で effect 再実行。

### #4 ダブルス hit_zone 7/8/9 衝突
前回 PR でダブルス時 Digit7/8/9/0 を hitter 選択にバインドしたが、結果 hit_zone
override の 7/8/9 が奪われていた。

修正:
- `useKeyboard.ts` で **Shift+Digit1-9 をダブルス時の hit_zone エスケープ**として追加
- AnnotatorPage の hit_zone ヒント表示を `store.isDoubles` で条件分岐:
  - シングルス: `打点: トップ行 1-9`
  - ダブルス: `打点: 1-6 ／ 7-9 は Shift+7-9`

### #3 land_zone 方向警告の視点反転バグ
旧: `currentPlayer === 'player_b'` だけで「自コート↓」固定 → コートチェンジ後
矛盾 (CourtDiagram は `playerSides` を見る)。

新: `computePlayerASide(playerAStart, ...)` で実際のコート位置を計算し、
ヘッダーラベルを動的生成:
- `t('annotator.land_zone_label_with_dir', { dir: '↑' or '↓' })`
- 色は `currentPlayer === 'player_b'` 判定でオレンジ/青を維持 (既存の意味)

### #5 autoSave エラー経路
旧: `localStorage.setItem` の例外を握り潰し、UI には何も出ない (`'未保存'` で固まる)。

新:
- `autoSaveError: string | null` state を追加
- try/catch で `QuotaExceededError` 等を判別し、`t('annotator.ui.autosave_quota')` /
  `t('annotator.ui.autosave_failed')` をセット
- スコアボード横の自動保存ステータス表示で **autoSaveError 優先** で赤色表示
  `⚠ 一時保存の容量超過` 等

### #6 alert() / window.confirm() を styled modal に置換
新コンポーネント: `src/components/common/Notice.tsx`
- `<NoticeBanner>` (toast 型エラー/通知バナー、自動 dismiss + ESC + ×ボタン)
- `<ConfirmDialog>` (モーダル確認、destructive オプション、ESC + バックドロップで cancel)

AnnotatorPage で:
- 14 件の `alert(...)` をすべて `setNotice({ kind: 'error', message: ... })` に置換
  → `<NoticeBanner>` で表示
- 3 件の `window.confirm(...)` を `setPendingConfirm({ ... })` に置換
  → `<ConfirmDialog>` で表示
  - YOLO リセット 2 箇所 (destructive: true, confirmLabel: 'リセットする')
  - autoSave 復元 1 箇所 (destructive: false, confirmLabel: '復元する', cancelLabel: '破棄')

破壊的操作は赤系ボタン、通常確認は青系ボタンで色分け。

### #10 モバイル & 試合中モードで視点切替/最初サーバー
`SettingsModePanel.tsx` に「試合設定」セクションを追加 (`alwaysOpen={isWide}`):
- 解析対象 (A) の初期コート: `↑ 上` / `↓ 下` 段組
- 最初のサーバー (1セット目): `A` / `B` 段組

AnnotatorPage は `playerAStart` / `setPlayerAStart` と `match?.initial_server` /
`handleInitialServerChange` を渡す。

これでデスクトップでしか触れなかった 2 設定が、モバイル / 試合中モード /
タブレット (lg+) でもアクセス可能に。

### #2 ハードコード日本語の i18n 化 (background agent 並行作業)
`AnnotatorPage.tsx` に直書きの日本語を `i18n/ja.json` に逃がす。
新規キーは `annotator.ui.*` / `annotator.flow.*` 系列に追加。
en.json は触らない (annotator は ja-only 仕様)。

(完了状況は agent 完了後に追記)

## 検証

### 追加テスト
（utility classes test 既存 / 新規追加なし — UI 変更が中心、構造的回帰は build と既存テストで担保）

### 全体テスト
- vitest: PASS 確認待ち (実行ログ別途)
- electron-vite build: PASS 確認待ち
- 本番 health: 確認待ち

## 影響

- DB スキーマ変更: なし
- バックエンド変更: なし
- 既存ルート / ページ挙動: 全てフロント挙動の改善 (情報量変えず)
- 新規依存追加: なし

## 残スコープ (今 PR 後)

監査 27 件のうち未対応 17 件:
- #11-21 重要: ステップインジケータ差別化、Tab key hint、HitZoneSelector ラベル
  contrast、ShotTypePanel mobile keys 表示、`useKeyboard` stale closure リスク,
  Undo の step 別挙動説明、rally_end での player toggle 副作用、score renderer
  統合、shortcut legend 統合、end_type wrap、`戻る`/`未保存` のさらに細かい i18n
- #22-27 整合性: TopBarMenu vs SettingsModePanel ラベルキー drift、
  setHitter suffix string 脆弱性、CommandPalette setTimeout exec 一貫性
