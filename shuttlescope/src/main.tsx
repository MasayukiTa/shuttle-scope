import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/globals.css'
// Material Symbols (Outlined) サブセットフォント (3.8MB → 232KB)。
// scripts/subset_material_symbols.py で MIcon name="..." を grep して使用 icon のみ
// 含む subset を生成。新規 icon 追加時は同 script を再実行。
// 新規 UI のアイコンは @/components/common/MIcon 経由で利用する。
import './styles/material-symbols-subset.css'
// R43 honeypot bundle: 死コードとして bundle に残し、reverse engineer 検知に使う。
// この import は副作用 (console.debug 1 行) しか起こさない。
import './utils/legacyCompat'

// PWA 標準モードや Web Inspector を繋げない iOS 端末で render 前 throw が
// 起きると画面が白くなるだけで原因が見えない。window.onerror で拾って画面
// 最上部に banner として表示する (React の ErrorBoundary では捕捉できない
// 同期エラー / async unhandledrejection もここで捕捉する)。
if (typeof window !== 'undefined') {
  const showError = (label: string, msg: string) => {
    try {
      let bar = document.getElementById('__ss_error_bar__')
      if (!bar) {
        bar = document.createElement('div')
        bar.id = '__ss_error_bar__'
        bar.style.cssText =
          'position:fixed;top:0;left:0;right:0;z-index:99999;' +
          'padding:10px 14px;font:12px/1.4 -apple-system,sans-serif;' +
          'background:#7f1d1d;color:#fff;white-space:pre-wrap;' +
          'word-break:break-all;max-height:50vh;overflow:auto;' +
          'border-bottom:2px solid #f87171;' +
          // pointer-events:none — bar 自体は情報表示のみで操作不要。
          // auto のままだと max-height 50vh まで膨らんだとき画面上半分の
          // タップ (mobile calib 6 点設置等) を z=99999 で横取りしてしまう。
          'pointer-events:none'
        document.body.appendChild(bar)
      }
      const t = new Date().toISOString().slice(11, 19)
      bar.textContent = `[${t}] ${label}: ${msg}\n` + (bar.textContent || '')
    } catch { /* DOM 未準備時は無視 */ }
  }
  window.addEventListener('error', (e) => {
    const msg = (e.error && (e.error.stack || e.error.message)) || e.message || String(e)
    // cross-origin script の "Script error." 系は origin 不明 (lineno 0 / filename 空)
    // で実害なし。iOS Safari 共有シート等で自動発火するため抑止。
    const isGeneric = /^Script error\.?$/.test(msg)
    const noOrigin = !e.filename && (!e.lineno || e.lineno === 0)
    if (isGeneric && noOrigin) return
    showError('Error', `${msg}\n  at ${e.filename}:${e.lineno}:${e.colno}`)
  })
  window.addEventListener('unhandledrejection', (e) => {
    const reason: any = e.reason
    const msg = (reason && (reason.stack || reason.message)) || String(reason)
    // AbortError は video unmount/seek 時に必ず出る既知良性エラー。bar に
    // 出すと calib 出入りのたび煩雑になるので suppress (error-reporter.js
    // 側でも同じ suppress を実装している)。
    if (reason && reason.name === 'AbortError') return
    if (/The operation was aborted/i.test(msg)) return
    showError('PromiseRejection', msg)
  })
}

// Material Symbols フォント (3.9 MB) ロード前に MIcon の raw テキスト
// ("play_arrow" 等) が見えてしまうのを防ぐ。fonts.ready で `ss-fonts-ready` を
// body に付与し、CSS 側で .material-symbols-outlined を visibility:hidden で隠す。
//
// ⚠️ 1.2 秒経過してもロード完了しなければ諦めて表示する (= "アイコン全消失で
// 画面が極端に遅く見える" 問題を防ぐ)。フォントが間に合わない場合は raw text が
// 一瞬出るが、空白 5 秒よりは UX 上はるかにマシ。
if (typeof document !== 'undefined' && (document as any).fonts) {
  const fontsApi = (document as any).fonts
  const markReady = () => {
    if (document.body) document.body.classList.add('ss-fonts-ready')
    else document.addEventListener('DOMContentLoaded', markReady)
  }
  // 既にロード済 (= キャッシュ) なら即座に
  try {
    if (typeof fontsApi.check === 'function' &&
        fontsApi.check('24px "Material Symbols Outlined"')) {
      markReady()
    }
  } catch { /* ignore */ }
  // ready Promise 解決時
  if (fontsApi.ready) {
    fontsApi.ready.then(markReady).catch(markReady)
  }
  // ハードタイムアウト: 1.2 秒で諦める
  setTimeout(markReady, 1200)
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
