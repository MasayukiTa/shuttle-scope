/**
 * Round 258 R33 fix (R6 deferred P1): hidden recorder window 専用 preload。
 *
 * 用途:
 *   electron/main.ts の `_ytRecorderWindow` (YouTube DRM / generic screen capture
 *   それぞれ 1 個) は、これまで `nodeIntegration: true + contextIsolation: false`
 *   で構築し、`executeJavaScript` 内で直接 `require('electron')` を呼び ipcRenderer
 *   を使っていた。これは Electron security best practice (= renderer から require
 *   不可、contextIsolation 必須) に反し、renderer XSS 経路で recorder window が
 *   node API を取られると任意ファイル書込み等に拡張する経路があった。
 *
 * 本 preload では:
 *   - `nodeIntegration: false / contextIsolation: true / sandbox: true` で recorder
 *     window を構築できるようにする
 *   - main プロセスとの通信は `contextBridge.exposeInMainWorld('recorderApi', ...)`
 *     経由で **start / sendChunk / sendError / onStop** だけ露出する
 *
 * IPC channel (main <-> recorder hidden window) は現在 main.ts に存在する
 *   - `youtube-drm-chunk` (Uint8Array → main へ chunk 転送)
 *   - `youtube-drm-error` (string → エラー報告)
 *   - `youtube-drm-stop` (main → recorder; user stop 要求)
 * を再利用する。チャンネル名は変えない (main 側ハンドラ互換のため)。
 */

import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('recorderApi', {
  /**
   * MediaRecorder の chunk を main プロセスに転送する。
   * data は ArrayBuffer。
   */
  sendChunk: (data: ArrayBuffer): void => {
    ipcRenderer.send('youtube-drm-chunk', data)
  },

  /**
   * エラーメッセージを main プロセスに転送する。
   */
  sendError: (msg: string): void => {
    ipcRenderer.send('youtube-drm-error', String(msg))
  },

  /**
   * main プロセスからの stop イベントを購読する。
   * 戻り値は unsubscribe 関数。
   */
  onStop: (cb: () => void): (() => void) => {
    const handler = () => cb()
    ipcRenderer.on('youtube-drm-stop', handler)
    return () => ipcRenderer.removeListener('youtube-drm-stop', handler)
  },
})
