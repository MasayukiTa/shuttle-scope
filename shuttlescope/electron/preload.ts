import { contextBridge, ipcRenderer } from 'electron'

// ─── Phase B4: Preload API セキュリティレビュー ────────────────────────────
//
// このファイルは renderer (信頼境界の外) からアクセス可能な API を全て定義する。
// 公開している API は以下のカテゴリのみ:
//   1. ユーザーが明示的にトリガする操作 (ファイル選択、録画保存)
//   2. 表示のみ (ディスプレイ一覧、バックエンドログ参照)
//   3. ウィンドウ間メッセージング (mirror-broadcast)
//   4. YouTube Live DRM キャプチャ (Phase 1 で追加、token 認可付き)
//
// 公開してはならないもの:
//   - 任意のシェルコマンド実行
//   - 任意のファイルシステム読み書き (open-video-file は dialog 必須)
//   - 任意の URL fetch (CSP / CORS バイパスになる)
//   - シークレット (SS_OPERATOR_TOKEN 等) の取得
//   - app.getPath('userData') 等の絶対パス情報
//
// 入力検証は main 側 (electron/main.ts) で行うこと。preload は単なる橋渡し。

contextBridge.exposeInMainWorld('shuttlescope', {
  version: process.env.npm_package_version ?? '1.0.0',
  platform: process.platform,
  openVideoFile: (): Promise<string | null> =>
    ipcRenderer.invoke('open-video-file'),

  // ─── ディスプレイ管理 ────────────────────────────────────────────────────────
  getDisplays: (): Promise<Array<{
    id: number
    label: string
    isPrimary: boolean
    bounds: { x: number; y: number; width: number; height: number }
  }>> =>
    ipcRenderer.invoke('get-displays'),

  openVideoWindow: (src: string, displayId: number, startTime?: number, paused?: boolean, matchId?: string): Promise<void> =>
    ipcRenderer.invoke('open-video-window', src, displayId, startTime ?? 0, paused ?? false, matchId),

  closeVideoWindow: (): Promise<void> =>
    ipcRenderer.invoke('close-video-window'),

  // ─── メインプロセスからのイベント受信 ───────────────────────────────────────
  onVideoWindowClosed: (cb: () => void) => {
    ipcRenderer.on('video-window-closed', () => cb())
    return () => ipcRenderer.removeAllListeners('video-window-closed')
  },

  // ─── P5: WebView フレームキャプチャ（実験的）────────────────────────────────
  captureWebviewFrame: (): Promise<string | null> =>
    ipcRenderer.invoke('capture-webview-frame'),

  // ─── 録画データ保存ダイアログ ──────────────────────────────────────────────
  saveRecordedVideo: (data: Uint8Array, defaultFilename: string): Promise<string | null> =>
    ipcRenderer.invoke('save-recorded-video', data.buffer, defaultFilename),

  // ─── アプリ再起動 ────────────────────────────────────────────────────────────
  restartApp: (): Promise<void> =>
    ipcRenderer.invoke('relaunch-app'),

  // ─── YouTube Live DRM キャプチャ (legacy: youtube ドメイン専用) ───────────────
  youtubeLiveDrmStart: (url: string, jobId: string, token: string): Promise<{ sourceId: string; sourceName: string }> =>
    ipcRenderer.invoke('youtube-live-drm-start', url, jobId, token),
  youtubeLiveDrmStop: (): Promise<void> =>
    ipcRenderer.invoke('youtube-live-drm-stop'),

  // ─── 汎用 画面キャプチャ録画 (任意 https URL 対応、会員限定 DRM 配信用) ──────
  // ライセンスされた視聴の OS-level 録画。CDM / DRM bypass はしない。
  // quality: 'low' (1.5Mbps/480p) / 'med' (5Mbps/720p, 既定) / 'high' (9Mbps/1080p)
  screenCaptureStart: (opts: { url: string; jobId: string; token: string; matchId?: number | null; quality?: 'low' | 'med' | 'high' }): Promise<{ sourceId: string; sourceName: string; hostname: string; quality: 'low' | 'med' | 'high' }> =>
    ipcRenderer.invoke('screen-capture-start', opts),
  screenCaptureStop: (): Promise<void> =>
    ipcRenderer.invoke('screen-capture-stop'),

  // ─── バックエンドログ ─────────────────────────────────────────────────────────
  getBackendLog: (): Promise<string[]> =>
    ipcRenderer.invoke('get-backend-log'),
  onBackendLog: (cb: (line: string) => void) => {
    const handler = (_: Electron.IpcRendererEvent, line: string) => cb(line)
    ipcRenderer.on('backend-log', handler)
    return () => ipcRenderer.removeListener('backend-log', handler)
  },

  // ─── 別モニタミラー: ウィンドウ間メッセージブローカ ────────────────────────
  // BroadcastChannel が Electron の別 BrowserWindow 間で確実に届かないため、
  // main プロセスをハブに使った IPC で代替する。
  sendMirror: (payload: unknown) => ipcRenderer.send('mirror-broadcast', payload),
  onMirror: (cb: (payload: unknown) => void) => {
    const handler = (_: Electron.IpcRendererEvent, payload: unknown) => cb(payload)
    ipcRenderer.on('mirror-message', handler)
    return () => ipcRenderer.removeListener('mirror-message', handler)
  },
})
