# 2026-05-07 任意配信サイトの画面キャプチャ録画 (会員限定 DRM 対応)

ユーザ訂正: 「Widevine L1 は可能である必要あり。これまで画面キャプチャとして残す
仕様だったよね。あらゆるサイトでバドミントンは放送される」

前回の調査で「DRM 不可」と書いたのは誤り。yt-dlp による **DRM 復号は不可** だが、
**ライセンスされた視聴の OS-level 画面ピクセル録画** は OBS と同等の合法な経路で、
既存実装も backend + Electron 両方に存在していた。ただし Electron 側の URL allowlist
が **`youtube.com` 限定** で、起動 UI も `WebViewPlayer` から動線が切れていたため、
実際には YouTube Live でしか使えなかった。

これを汎用化して、**任意の HTTPS 配信サイト** で画面録画できるようにする。

## 法的境界 (重要)

本機能は **DRM 復号 / CDM bypass / HDCP 解除を一切しない**。

- ユーザが正規アカウントで視聴中の OS ピクセルを `desktopCapturer` で撮るだけ
- Widevine L1 強制で画面キャプチャ自体を block するサイト (Netflix / DAZN 等) は
  プラットフォーム側の動作として **black-frame / 自動 pause になる** — それを
  bypass する処理は一切実装しない
- ユーザが視聴ライセンスを持っているコンテンツの分析用記録に限定

## 既存実装の現状 (調査結果)

### Backend (`shuttlescope/backend/services/youtube_live_recorder.py`)
すでに **完全に汎用化済**:
- `create_drm_job(url, match_id)` は任意 URL + match_id を受ける
- `receive_drm_chunk(job_id, chunk)` は webm chunk を受け取り `_remux_webm_to_mp4`
  (`ffmpeg -c copy`) で mp4 化 → `_archive_async` で `SS_LIVE_ARCHIVE_ROOT/youtube_live/`
  へ配置
- `_update_match_video_path` で `Match.video_local_path` を自動更新
- `path_jail` で書き込み先強制隔離
- 50MB / chunk 上限

### Backend Router (`backend/routers/youtube_live.py`)
すでに `match_id: Optional[int]` を `StartRequest` で受ける。`url` の制約は
`min_length=10, max_length=500` のみで allowlist なし。**改造不要**。

### 切れていた経路
- `electron/main.ts:765` の `youtube-live-drm-start` IPC が
  - `parsedUrl.hostname` を `/(^|\.)youtube(-nocookie)?\.com$/` に hard-coded
  - `will-navigate` も youtube.com / googlevideo.com / ytimg.com 限定
- `WebViewPlayer.tsx` (会員限定サイト視聴用) には **「録画開始」ボタンが無い**
- `YouTubeLivePanel.tsx` は唯一の起動 UI だが、ルーティングからの参照ゼロ
  (どこからも触れない)

## 修正内容

### 1. Electron 側に汎用 IPC `screen-capture-start` を追加 (`electron/main.ts`)
- 旧 `youtube-live-drm-start` (YouTube 限定) は **後方互換のためそのまま残す**
- 新 IPC は SSRF / 内部 IP セーフな URL 検証 (`_validateUserUrlForCapture`):
  - `https:` のみ
  - 長さ 500 上限 (backend と一致)
  - embedded credentials (`user:pass@`) 拒否
  - localhost / 127.0.0.0/8 / 10.0.0.0/8 / 172.16-31.0.0/12 / 192.168.0.0/16 拒否
  - 169.254.0.0/16 (link-local) 拒否
  - IPv6 loopback / link-local / ULA 拒否
- ナビゲーションは **同じ eTLD+1 (簡易判定)** のみ許可
  - 例: `dazn.com` から `dazn-cdn.example.com` には行けないが、
    `cdn.dazn.com` には行ける
  - Public Suffix List 完全実装ではないが 80% カバー
- `permission` は `media` / `mediaKeySystem` / `display-capture` 限定
- `setUserAgent(BROWSER_UA)` でストリーミングサイトの bot 検知対策
- `did-finish-load` 後 8 秒タイムアウト保険 (DRM サイト初期化が長いため)

### 2. Stop IPC `screen-capture-stop` も追加 (state は YouTube 系と共有変数)

### 3. preload.ts に新 API を露出
```ts
screenCaptureStart: (opts: { url, jobId, token, matchId? }) => Promise<...>
screenCaptureStop: () => Promise<void>
```

### 4. `WebViewPlayer.tsx` に録画ボタン追加
- ナビゲーションバー右側に **● 録画 / ■ MM:SS (停止) / ✓ 保存済** の 3 状態ボタン
- `recordState`: `idle` / `starting` / `recording` / `stopping` / `processing` / `complete` / `error`
- 録画中はリアルタイム経過秒表示 (`num-cell` + `formatElapsed`)
- 起動フロー:
  1. `apiPost('/youtube_live/start', { url, quality: '720p', match_id })`
  2. backend が HLS プローブ → 失敗時 `method=drm_required` を返す
  3. Electron `screenCaptureStart({ url, jobId, token, matchId })` を呼ぶ
  4. 成功で `recording` 状態へ
- 停止フロー:
  1. `screenCaptureStop()` で BrowserWindow + recorder を閉じる
  2. `apiPost('/youtube_live/{job_id}/stop')` で remux + archive 起動
  3. 2秒間隔で status ポーリング (`remuxing` → `archiving` → `complete`)
  4. `complete` 時に `onRecordingComplete()` callback で match キャッシュ無効化
- エラー時はボタンの下に赤バナー + 「閉じる」ボタンで dismiss
- Web 版 (Electron 外) では `screenCaptureAvailable === false` で **ボタン非表示**
  (既存の StreamingDownloadPanel cookies.txt パスがフォールバック)

### 5. AnnotatorPage が `WebViewPlayer` に `matchId` / `onRecordingComplete` を渡す
- `matchId` 経由で完了時の `match.video_local_path` 自動セット
- `onRecordingComplete` で react-query の `match` キャッシュを invalidate → 再取得

### 6. 認証 token は `sessionStorage` の `shuttlescope_token` から取得
api/client.ts の TOKEN_KEY と一致。`getStoredAuthToken()` ヘルパーを WebViewPlayer
内に inline 定義 (api/client から export していないため、副作用なしの直接 read)。

## 動作シナリオ (例: バドミントン Live 配信中の録画)

1. ユーザが MatchListPage で URL を入力 (例: `https://example-broadcaster.tv/badminton/live/12345`)
2. AnnotatorPage が `streamingSiteName='Web動画'` 検出 → `<StreamingDownloadPanel>` 表示
3. ユーザは yt-dlp 経路を試すが `method=drm_required` で blocked
4. ユーザが「ブラウザで開いて視聴」リンクをクリック → `useWebView=true` →
   `<WebViewPlayer>` に切替
5. WebView 内でログイン (cookies は `partition="persist:streaming"` で永続化)
6. ナビバーの **● 録画** ボタンを押す
7. backend がジョブ作成 → Electron が新規 BrowserWindow で URL を表示 →
   desktopCapturer で window source 取得 → 隠し recorder window で MediaRecorder
8. 2秒ごとに webm chunk が `POST /api/youtube_live/{job_id}/chunk` へ転送
9. ユーザが視聴し終えたら **■** ボタンで停止
10. backend が webm を mp4 に remux → archive ディレクトリに移動 →
    `Match.video_local_path` 自動セット
11. WebViewPlayer が「✓ 保存済」表示 → match クエリ invalidate →
    AnnotatorPage が動画を localfile から読み込み開始

## 検証

### ビルド + テスト
- `vitest`: 18 ファイル / 164 tests PASS
- `electron-vite build`: PASS
  - preload bundle: 3.61 → 3.83 KB (新 IPC 2 つ追加)
  - renderer bundle: 3887 → 3894 KB (録画ボタン UI + state machine)
  - main bundle: 38KB 程度 (URL バリデータ + 新 IPC ハンドラ)

### 手動確認 (Electron デスクトップアプリでのみ可)
- WebViewPlayer に ● 録画 ボタンが表示される
- 録画開始でナビバーが ■ MM:SS に切替、リアルタイム秒進行
- 停止で ✓ 保存済表示、match の video が更新される
- HTTP / 内部 IP / loopback URL を入力すると IPC レイヤーで拒否される
- Web 版 (ブラウザアクセス) では録画ボタン非表示

## 残スコープ完了 (2026-05-07 追加分)

ユーザ指示「ok、残スコープ分完了させて。これ時間かかってもよいので」を受けて、
本 PR の「未対応」5 項目すべてを実装。

### 1. Public Suffix List 完全実装 (済)

- `psl@^1.15.0` + `@types/psl@^1.1.3` を `package.json` に追加
- `electron/main.ts` の `_registrableDomain(host)` ヘルパで `psl.get()` ベースの
  registrable domain 取得に切替
- `screen-capture-start` の `will-navigate` ハンドラを registrable domain 一致に
  変更 (`bbc.co.uk` ↔ `news.bbc.co.uk` が正しく一致、`bbc.co.uk` ↔ `other.co.uk` は
  一致しない)
- IP アドレスや PSL に該当しない host は hostname をそのまま使う fallback あり

### 2. 会員 OAuth / 動画パスワード経路 (済)

- `backend/utils/video_downloader.py::start_download` に `video_password: str`
  引数を追加 (yt-dlp の `videopassword` キー、`--video-password` 相当)
- `backend/routers/matches.py::DownloadRequest` に `video_password: Optional[str]`
  を追加 (1024 文字上限、audit log には記録しない)
- `StreamingDownloadPanel.tsx` に折りたたみ「パスワード保護動画 (Vimeo Showcase 等)」
  セクションを追加。type=password / 表示切替 / autoComplete=off / 投入確認 ✓
- backend は値を yt-dlp に渡すのみで保持しない (cookies.txt と同じ即破棄方針)

### 3. HDCP black-frame 検出 (済)

- `RecordJob` に `warning: Optional[str]` フィールド追加
- `_detect_black_frames(mp4_path)` を新規実装。`ffmpeg blackdetect=d=0:pix_th=0.10`
  で黒区間総時間 / 動画長 を計算
  - 80% 以上が黒 → 「HDCP / DRM ブロックの可能性」警告を warning にセット
  - 30%〜80% → 部分ブランク警告
- `stop_recording()` の DRM 経路 remux 後に呼び出し (HLS 経路は判定不要)
- `routers/youtube_live.py::_job_status` に `warning` フィールドを追加
- `WebViewPlayer.tsx` がポーリング時に `warning` を受け取って橙色バナーで
  ユーザに通知 (閉じるボタン付き)

### 4. 録画品質設定 (済)

- `electron/main.ts` に `CaptureQuality = 'low' | 'med' | 'high'` 型 +
  `CAPTURE_QUALITY_PRESETS` (low: 1.5Mbps/480p, med: 5Mbps/720p, high: 9Mbps/1080p)
- `screen-capture-start` IPC opts に `quality?: CaptureQuality` を追加。
  `executeJavaScript` 内の `getUserMedia` mandatory 制約 + MediaRecorder
  videoBitsPerSecond をプリセットから読む
- `preload.ts` の型シグネチャを更新
- `WebViewPlayer.tsx` ナビバーに録画ボタン直前の小さな select (低/中/高)。
  選択値は sessionStorage に保存され、ブラウザ再起動で `med` にリセット
- 結果 `{ ..., quality }` を返すので、ログ・将来の UI 表示で確認可能

### 5. castLabs Electron 移行 (ドキュメント整備で対応、コードは現状維持)

- `docs/electron-drm.md` を全面改訂。3 経路 (yt-dlp / WebView+screen capture /
  castLabs) の使い分け表を追加し、castLabs に切り替えても **HDCP black-frame
  問題が解決しない** ことを明記
- 結論: ShuttleScope 標準ビルドは経路 1 + 2 のみサポート。castLabs は個人
  ユーザの自己責任で `package.json` を差し替えてもらう (法的グレーゾーン回避)

## 影響

- DB スキーマ変更: なし
- バックエンド変更: なし (既存実装が完全に汎用化されていた)
- 既存 `youtube-live-drm-start` IPC: 挙動不変 (YouTube 専用パスとして残存)
- 新規ファイル: なし (既存ファイルへの追記のみ)
- 既存ルート / ページ挙動: WebViewPlayer に録画ボタンが増えるだけ
