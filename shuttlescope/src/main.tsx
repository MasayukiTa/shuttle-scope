import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/globals.css'
// Material Symbols (Outlined) ローカルフォント。CSP / 外部 CDN 不要。
// 新規 UI のアイコンは @/components/common/MIcon 経由で利用する。
import 'material-symbols/outlined.css'
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
          'border-bottom:2px solid #f87171'
        document.body.appendChild(bar)
      }
      const t = new Date().toISOString().slice(11, 19)
      bar.textContent = `[${t}] ${label}: ${msg}\n` + (bar.textContent || '')
    } catch { /* DOM 未準備時は無視 */ }
  }
  window.addEventListener('error', (e) => {
    const msg = (e.error && (e.error.stack || e.error.message)) || e.message || String(e)
    showError('Error', `${msg}\n  at ${e.filename}:${e.lineno}:${e.colno}`)
  })
  window.addEventListener('unhandledrejection', (e) => {
    const reason: any = e.reason
    const msg = (reason && (reason.stack || reason.message)) || String(reason)
    showError('PromiseRejection', msg)
  })
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
