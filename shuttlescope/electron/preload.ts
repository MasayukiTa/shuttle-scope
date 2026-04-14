import { contextBridge, ipcRenderer } from 'electron'

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
