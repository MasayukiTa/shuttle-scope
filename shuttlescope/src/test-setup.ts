import '@testing-library/jest-dom'
import { vi } from 'vitest'

// Electron API のモック（Electron 環境外で実行するため）
Object.defineProperty(window, 'shuttlescope', {
  value: {
    version: '1.0.0',
    platform: 'test',
    openVideoFile: vi.fn().mockResolvedValue(null),
  },
  writable: true,
})

// <webview> は Electron 独自要素。jsdom では HTMLUnknownElement として扱われるが
// canGoBack / canGoForward / reload / goBack / goForward メソッドが必要なため
// プロトタイプに追加しておく。
// ※ customElements.define('webview', ...) は "webview" がハイフンなしのため
//   Web 標準上無効 → DOMException になるので使わない。
Object.assign(HTMLUnknownElement.prototype, {
  canGoBack: () => false,
  canGoForward: () => false,
  goBack: () => {},
  goForward: () => {},
  reload: () => {},
})
