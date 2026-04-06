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

  openVideoWindow: (src: string, displayId: number): Promise<void> =>
    ipcRenderer.invoke('open-video-window', src, displayId),

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
})
