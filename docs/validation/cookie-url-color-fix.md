# Validation: Cookie DB ロック回避 & URL文字色修正 & SSL自動リトライ & ライト/ダークモード修正

## 変更ファイル
- `shuttlescope/src/components/video/StreamingDownloadPanel.tsx`
- `shuttlescope/backend/utils/video_downloader.py`

## 変更内容

### 1. URL文字色修正（StreamingDownloadPanel.tsx:179）
- `text-gray-400` → `text-white`
- 背景 `bg-gray-900/60`（濃い灰色）に対して文字が見えなかった問題を解消

### 2. Cookie DB ロック回避（video_downloader.py）
**問題**: Edge/Chrome を閉じても `msedgewebview2.exe`（WebView2）が常駐しており、Cookie SQLite DB をロックし続けるため yt-dlp の `shutil.copy2` が失敗する。

**修正内容**:
- `_make_unlocked_profile_copy(browser)` 関数を追加
  - sqlite3 の `?immutable=1` URI モードでロックを無視してDBを読み込み
  - `conn.backup()` でアンロックされたコピーを tmpdir に作成
  - `Local State`（DPAPI暗号化キー）も tmpdir にコピー
  - yt-dlp の `cookiesfrombrowser = (browser, tmpdir)` でコピーを参照させる
  - ダウンロード後に tmpdir を削除（cleanup）
- エラーメッセージに `msedgewebview2.exe` の終了と `pip install -U yt-dlp` の案内を追加
- 演算子優先度バグ修正: `or ... or ... and ...` → `or (... and ...)` で括弧明示

### 3. URL文字色 inline style 化（StreamingDownloadPanel.tsx:179）
- `text-white` クラスは globals.css の `html[data-theme="light"] .text-white { color: #0f172a !important; }` に上書きされていた
- `style={{ color: '#fff' }}` の inline style に変更してテーマ上書きを回避

### 4. SSLエラー誤分類修正 & 自動リトライ（video_downloader.py）
- `CERTIFICATE_VERIFY_FAILED` エラーが "cookie" キーワードを含む文字列内で後に出現し、Cookieエラーとして誤分類されていた
- `_format_error` にSSL検出を **最優先ブロック** として追加（`if` → SSL, `elif` → ffmpeg, `elif` → Cookie...）
- `_download_sync` にSSL自動リトライを実装: SSL証明書エラー時に `nocheckcertificate: True` で再試行
- `_is_ssl_error()` ヘルパーを追加して判定を共通化

## 検証方法
1. Edge/Chrome が起動中（またはWebView2常駐中）の状態で YouTube URL を入力
2. Cookieブラウザに Edge または Chrome を選択してダウンロード開始
3. 従来: "Could not copy Chrome cookie database" エラー → 修正後: immutableコピーで継続
4. URL表示部分が白文字(`#fff` inline)で視認できることを確認（ライト/ダーク両モード）
5. 企業プロキシ環境でSSL証明書エラーが出た場合、自動で `nocheckcertificate` リトライされることを確認

### 5. ライト/ダークモード完全対応（StreamingDownloadPanel・WebViewPlayer・globals.css）

**根本原因**: 両コンポーネントが `useIsLightMode()` フックを使っておらず、全クラスがダークテーマ専用にハードコードされていた。

**修正内容**:
- `StreamingDownloadPanel.tsx`: `useIsLightMode()` を導入し、outer bg・URL box・各バナー（orange/yellow/green/red/blue）・セレクト・テキスト色をすべて `isLight ? lightClass : darkClass` で明示分岐
- `WebViewPlayer.tsx`: `useIsLightMode()` を導入し、ナビバー・タイトルバー・URL入力・エラーバナー・ボタンをすべてテーマ分岐
- `globals.css`: 欠落していた透明度付きクラスを追加:
  - `bg-gray-800/60`, `bg-gray-800/90`, `bg-gray-900/60`, `bg-gray-900/90`
  - `bg-orange-900/20`, `border-orange-700/40`
  - `bg-blue-900/20`
  - `border-yellow-700/40`

**ビルド確認**: `npm run build` 成功（エラーなし）
