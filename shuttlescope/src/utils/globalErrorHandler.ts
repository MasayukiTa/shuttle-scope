import i18n from '@/i18n'

/**
 * window の error / unhandledrejection を拾って画面上部に帯を出す。
 *
 * - 開発ビルド (showDetails=true): 従来どおり stack / ファイル位置を追記表示する。
 * - 本番ビルド (showDetails=false): 内部の関数名・URL・bundle 位置を利用者に見せない。
 *   一般向けの文言とエラー ID だけを 1 行で出し、一定時間で消す。詳細はコンソールにのみ残る。
 *   (ErrorBoundary の本番表示と同じ方針。同じ翻訳キーを使う。)
 */

export const GLOBAL_ERROR_BAR_ID = '__ss_error_bar__'

/** 本番で帯を残す時間 (ミリ秒)。通常操作を覆い続けないため。 */
const PUBLIC_BAR_VISIBLE_MS = 10_000
/** 同じ内容のエラーを再表示しない時間 (ミリ秒)。連続発火での入れ替わりを防ぐ。 */
const DEDUPE_WINDOW_MS = 5_000

export function makeGlobalErrorId(): string {
  return `E-${Date.now().toString(36).toUpperCase()}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`
}

export interface GlobalErrorHandlerOptions {
  /** 詳細を画面に出すか。既定は開発ビルドだけ。 */
  showDetails?: boolean
}

type RejectionReason = { stack?: string; message?: string; name?: string } | null | undefined

export function installGlobalErrorHandlers(options: GlobalErrorHandlerOptions = {}): () => void {
  if (typeof window === 'undefined') return () => {}
  const showDetails = options.showDetails ?? import.meta.env.DEV
  let hideTimer: ReturnType<typeof setTimeout> | null = null
  let lastSignature = ''
  let lastAt = 0

  const getBar = (): HTMLElement | null => {
    let bar = document.getElementById(GLOBAL_ERROR_BAR_ID)
    if (!bar) {
      bar = document.createElement('div')
      bar.id = GLOBAL_ERROR_BAR_ID
      bar.style.cssText =
        'position:fixed;top:0;left:0;right:0;z-index:99999;' +
        'padding:10px 14px;font:12px/1.4 -apple-system,sans-serif;' +
        'background:#7f1d1d;color:#fff;white-space:pre-wrap;' +
        'word-break:break-all;max-height:50vh;overflow:auto;' +
        'border-bottom:2px solid #f87171;' +
        // 帯自体は情報表示のみ。auto のままだと画面上部のタップを z=99999 で横取りする。
        'pointer-events:none'
      document.body.appendChild(bar)
    }
    return bar
  }

  const report = (label: string, detail: string) => {
    const errorId = makeGlobalErrorId()
    // 詳細はコンソールにだけ残す (本番でも開発でも)。
    console.error('[GlobalError]', errorId, label, detail)
    try {
      const signature = `${label}:${detail.slice(0, 200)}`
      const now = Date.now()
      if (!showDetails && signature === lastSignature && now - lastAt < DEDUPE_WINDOW_MS) return
      lastSignature = signature
      lastAt = now
      const bar = getBar()
      if (!bar) return
      if (showDetails) {
        const t = new Date().toISOString().slice(11, 19)
        bar.textContent = `[${t}] ${label}: ${detail}\n` + (bar.textContent || '')
        return
      }
      bar.textContent =
        `${i18n.t('error_boundary.public_message')} ` +
        `${i18n.t('error_boundary.error_id_label')}: ${errorId}`
      if (hideTimer) clearTimeout(hideTimer)
      hideTimer = setTimeout(() => {
        const el = document.getElementById(GLOBAL_ERROR_BAR_ID)
        if (el) el.remove()
        hideTimer = null
      }, PUBLIC_BAR_VISIBLE_MS)
    } catch { /* DOM 未準備時は無視 */ }
  }

  const onError = (e: ErrorEvent) => {
    const msg = (e.error && (e.error.stack || e.error.message)) || e.message || String(e)
    // cross-origin script の "Script error." 系は origin 不明 (lineno 0 / filename 空)
    // で実害なし。iOS Safari 共有シート等で自動発火するため抑止。
    const isGeneric = /^Script error\.?$/.test(msg)
    const noOrigin = !e.filename && (!e.lineno || e.lineno === 0)
    if (isGeneric && noOrigin) return
    report('Error', `${msg}\n  at ${e.filename}:${e.lineno}:${e.colno}`)
  }
  const onRejection = (e: PromiseRejectionEvent) => {
    const reason = e.reason as RejectionReason
    const msg = (reason && (reason.stack || reason.message)) || String(reason)
    // AbortError は video unmount/seek 時に必ず出る既知良性エラー。
    if (reason && reason.name === 'AbortError') return
    if (/The operation was aborted/i.test(msg)) return
    report('PromiseRejection', msg)
  }

  window.addEventListener('error', onError)
  window.addEventListener('unhandledrejection', onRejection)
  return () => {
    window.removeEventListener('error', onError)
    window.removeEventListener('unhandledrejection', onRejection)
    if (hideTimer) clearTimeout(hideTimer)
  }
}
