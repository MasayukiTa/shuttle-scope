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
import { startTelemetry } from './utils/analytics'
import { installGlobalErrorHandlers } from './utils/globalErrorHandler'

// PWA 標準モードや Web Inspector を繋げない iOS 端末で render 前 throw が
// 起きると画面が白くなるだけで原因が見えない。window.onerror で拾って画面
// 最上部に banner として表示する (React の ErrorBoundary では捕捉できない
// 同期エラー / async unhandledrejection もここで捕捉する)。
// 本番では stack / ファイル位置を出さず、一般向けの文言とエラー ID だけを出す
// (詳細はコンソールのみ)。実装は utils/globalErrorHandler.ts。
installGlobalErrorHandlers()

// Material Symbols フォント (3.9 MB) ロード前に MIcon の raw テキスト
// ("play_arrow" 等) が見えてしまうのを防ぐ。fonts.ready で `ss-fonts-ready` を
// body に付与し、CSS 側で .material-symbols-outlined を visibility:hidden で隠す。
//
// ⚠️ 1.2 秒経過してもロード完了しなければ諦めて表示する (= "アイコン全消失で
// 画面が極端に遅く見える" 問題を防ぐ)。フォントが間に合わない場合は raw text が
// 一瞬出るが、空白 5 秒よりは UX 上はるかにマシ。
type FontFaceSetLike = {
  check?: (font: string) => boolean
  ready?: Promise<unknown>
}
const _docFonts: FontFaceSetLike | undefined = (document as unknown as { fonts?: FontFaceSetLike })?.fonts
if (typeof document !== 'undefined' && _docFonts) {
  const fontsApi = _docFonts
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

// 製品テレメトリ起動 (PRIVACY §テレメトリ; GDPR Art 6(1)(f) / APPI 第18条但書)
try { startTelemetry() } catch { /* ignore */ }

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
