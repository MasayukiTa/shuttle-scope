# 2026-05-07 アノテーター監査 残 13 件 + 動画 DL 拡張 一括対応

ユーザ指摘:
1. 監査 27 件のうち未対応 17 件を全部処理する
2. 現状の動画 DL 機能を確認、cookie 取得で会員限定サイト対応の見込み

実態は「既修正 4 件 + 未対応 13 件」。13 件すべて修正 + 動画 DL UI に
cookies.txt 経路を開通。

## 動画 DL 調査結果

### Backend は完成している
- `backend/utils/video_downloader.py` で yt-dlp 完全ラッパー
- `backend/routers/matches.py:1042-1153` で `/matches/{id}/download` が
  - `cookies_txt` (Netscape 形式) を受け付け、`/tmp/ss_cookies/<uuid>.txt`
    (mode 0o700/0o600) に保存 → yt-dlp `--cookiefile` に渡す → ジョブ終了で削除
  - `cookie_browser` (Chrome/Edge 等のローカルプロファイル直読み)
  両経路で 1MB 上限 / null byte / 制御文字 / Netscape ヘッダ存在チェックあり
- サイト allowlist は無く、yt-dlp が抽出器を持つサイト全部が backend 上は通る
- DRM (Widevine L1) は `_format_error` が検知してエラー化 (Netflix 等は不可)

### フロント側のギャップ (致命)
- `StreamingDownloadPanel.tsx` が POST する body は `{ quality, cookie_browser }` のみ
- **`cookies_txt` を送る経路が UI に無い** → Web 経由で会員限定サイト DL は不可だった
- Electron で `cookie_browser=chrome` を選べば動くが、Cloudflare 経由 Web では何も渡せない

### 修正
`StreamingDownloadPanel.tsx` に **cookies.txt ファイル投入 UI** を追加:
- file input (.txt accept)
- 1MB 上限チェック (backend と同じ)
- 簡易 Netscape ヘッダチェック
- `cookies_txt: text` を body に含めて POST
- 投入済表示 (ファイル名 + サイズ KB) + クリアボタン
- 案内テキスト「Cookie-Editor 等で書き出し → ここにアップ」

これで会員限定サイト DL が **Web 経由でも開通**。

### 未対応 (本 PR 範囲外、推奨対応順)
1. **任意 `http_headers`** (Referer / User-Agent / Authorization) を body に受けて
   `yt_opts["http_headers"]` に流す経路 — referer 必須サイト用 (難易度 M)
2. **Electron WebView session.cookies.get() → cookies.txt 自動エクスポート** —
   「ブラウザでログイン → そのまま DL」を 1 アクション化 (難易度 M)
3. **OAuth / video password 経路** — Twitch メンバー / Vimeo Showcase 等 (難易度 M)

## 監査残 13 件

### 重要 (8 件)

#### #11 ステップインジケータ差別化
旧: `idle` (待機中) と「ラリー中アイドル (ショット選択待ち)」が同じ灰色背景。
新: 4 状態を色分け。
- 待機 (idle + !isRallyActive): 灰
- ラリー中ショット待ち (idle + isRallyActive): 緑 emerald-300
- 着地点入力 (land_zone): 青
- ラリー終了 (rally_end): 橙

#### #12 Tab キーヒント
プレイヤー切替ボタンに `aria-keyshortcuts="Tab"` + 視認 kbd ピル `<kbd>Tab</kbd>`
を追加 (md+ のみ表示、モバイルは非表示)。tooltip も「プレイヤー切替 (Tab)」。

#### #13 HitZoneSelector override ラベル WCAG クリア
旧: `text-[10px] text-orange-400` (≈3.5:1, AA fail)
新: `text-xs (12px) + text-orange-300 + 丸枠 (border-orange-500/50 +
bg-orange-900/40)` で視認性大幅向上。`✎` プレフィックスでアイコン化。

#### #14 ShotTypePanel forceShowKeyHints prop + Settings トグル
- ShotTypePanel に `forceShowKeyHints` prop を追加 (true で md 未満でもキーヒント表示)
- AnnotatorPage に `forceShowKeyHints` state (localStorage `ss_show_key_hints_mobile` 永続化)
- SettingsModePanel に「キーヒント表示」セクション + `ToggleControl` 追加
- 両 SettingsModePanel 呼び出し (デスクトップ + BottomSheet) に props 配線

iPad ベンチで BT keyboard 接続して試合中入力する運用に対応。

#### #15 useKeyboard pendingEndType stale closure
`onWinnerSelect` が `pendingEndType` / `store.currentStrokes` を closure 経由で
参照していたが、`useKeyboard` の deps が `[videoRef]` のみで再バインドされない
ため stale リスクがあった。`pendingEndTypeRef` / `currentStrokesRef` で防衛的に
最新値を参照するよう修正。

#### #16 Undo の step 別挙動説明
旧: ボタンは「戻す (Ctrl+Z)」一律。step によって挙動が違う (idle=ストローク削除 /
land_zone=ペンディングキャンセル) のに UI で説明なし。
新: ステップ別にラベル + tooltip 動的化 + ボタン自体も land_zone 中なら
`cancelPendingStroke` を呼ぶ (キーボード挙動と一致)。

#### #21 rally_end で player toggle disabled
旧: `playerToggleDisabled = inputStep === 'land_zone'` のみ
新: `'land_zone' || 'rally_end'` で rally_end 中もブロック。クリックして
副作用なし問題を解消。

#### #27 keymap dual meaning hint
`0` キーが singles=skip / doubles=player_b 打者選択 で意味が違うのに UI 説明なし。
落点スキップボタンの tooltip を `store.isDoubles` で分岐し、ダブルス時は
「0 キーは player_b 打者選択に割当のためボタンのみ」と明示。

### 整合性 (3 件)

#### #22 3 つの score renderer 統合
新 `ScoreboardCompact` コンポーネントに集約:
- モバイルスティッキー (3415-3447) → 1 呼び出し
- デスクトップカード (3453-3484) → 1 呼び出し (timer は middleExtra slot)
- TopBarScore (上バー) は独立用途なので残す

`useLargeTouch` フラグで text-2xl / text-4xl + min-w 切替。selected 列の
title 属性で全文 hover 表示。

#### #23 shortcut legend 統合
新 `ShortcutLegend` コンポーネントに集約:
- サイドバーガイド (3127-3140) → `<ShortcutLegend variant="compact" />`
- Match Day Mode overlay (3327-3340) → `<ShortcutLegend variant="full" />`

`SHORTCUTS` 定数に 18 個のキー定義 (動画 / ラリー / ショット / 落点-打点 / メタ
の 5 セクション)。`hiddenInCompact` で上級者向けキー (Shift+1-9 doubles など)
を compact 時に間引き。drift 防止。

#### #24 TopBarMenu vs SettingsModePanel ラベルキー drift
TopBarMenu の annotation_mode / match_day_mode ボタンが
`t('annotation_mode.label')` / `t('annotator.match_day_mode')` を使い、
SettingsModePanel は `t('annotator.ux.settings_assist_label')` /
`t('annotator.ux.settings_match_day_label')` を使っていた。
TopBarMenu 側を Settings 側のキーに統一。

### 整合性 #26: setHitter explicit map
旧: `currentPlayer: (h === 'player_b' || h === 'partner_b') ? 'player_b' : 'player_a'`
の suffix 文字列マッチ。将来 hitter id に `_a` を含む別文字列が混入すると壊れる。
新: `HITTER_TO_TEAM` Record で明示的にマッピング、未知 hitter はデフォルト
`player_a` でフォールバック。

## 既修正 (round 2 で対応済、agent の指摘では「未対応」となっていた)

- #17 init エラー画面の `戻る` hardcoded → ✅ `t('annotator.ui.back')` 化済み
- #18 `land_zone 未入力ストロークがあります` hardcoded → ✅ i18n agent 移管済
- #19 `alert(...)` 14 件 → ✅ `<NoticeBanner>` 化済み
- #20 `window.confirm()` 3 件 → ✅ `<ConfirmDialog>` 化済み

## 検証

### テスト
- `vitest`: **18 ファイル / 164 tests PASS**
- electron-vite build: PASS (`NODE_OPTIONS=--max-old-space-size=16384`)
- modules 2906 → 2908 (+2: ScoreboardCompact + ShortcutLegend)

### 手動確認推奨
- ステップ別の色帯切替 (待機 灰 / ラリー中 緑 / land_zone 青 / rally_end 橙)
- Player 切替ボタンに Tab kbd ピルが表示
- HitZoneSelector で override 後にオレンジバッジが視認できる
- 設定で「モバイルでもキーヒント表示」を ON にすると ShotTypePanel に
  キー名が出る
- rally_end で プレイヤートグルが灰色 disabled になる
- mobile + desktop で score 表示が同一フォーマット
- ⋮ メニューと SettingsModePanel で同じラベル表記
- Streaming パネルで cookies.txt をアップして DL 開始可能 (UI 通る)

## 影響

- DB スキーマ変更: なし
- バックエンド変更: なし (cookies.txt 経路は backend 既存)
- 既存ルート / ページ挙動: UI 改善のみ
- 新規依存: なし
- 抽出した新規コンポーネント:
  - `src/components/annotator/ScoreboardCompact.tsx`
  - `src/components/annotator/ShortcutLegend.tsx`
  - (前回 PR で `src/components/common/Notice.tsx`)

## 残スコープ

監査からは全件対応完了。今後追加で発見されたら別ラウンドで対応。
動画 DL は **会員限定サイト Web 経由** が今 PR で開通。さらに高度な
http_headers / OAuth / Electron cookie 自動エクスポート は別ラインで。
