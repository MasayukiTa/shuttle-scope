import '@testing-library/jest-dom'
import { vi } from 'vitest'
// `b505952 Migrate annotation UI labels to i18n` 以降、ReviewQueuePanel /
// CVAssistPanel など多くのコンポーネントが `useTranslation()` を使用する。
// i18next は副作用付き init が走らないと t(key) が key をそのまま返すため、
// 翻訳済み Japanese 文字列を期待しているテストが軒並み失敗する。テスト環境で
// 必ず初期化済みになるよう、setup file から i18n をロードする。
//
// なお `detectInitialLang()` は jsdom 上では navigator.language=en-US を
// 拾って en になってしまうため、明示的に ja に切り替える (既存テストは
// 全て日本語文字列を期待している)。
import i18n from '@/i18n'
i18n.changeLanguage('ja')

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
