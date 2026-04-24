/**
 * WebViewPlayer — Electron <webview> を使ったインブラウザ動画プレイヤー
 *
 * 用途:
 *   - DRM保護コンテンツ（Widevine L3）の再生
 *   - yt-dlp でダウンロードできないログイン必須サイト
 *   - ブラウザ経由でのみ視聴可能な配信プラットフォーム
 *
 * 仕組み:
 *   - Electron の <webview> タグは独立した Chromium レンダラープロセスを起動する
 *   - partition="persist:streaming" でセッションCookieを永続化（ログイン状態を維持）
 *   - Widevine L3（ソフトウェアCDM）は Electron 20+ に内蔵されているため別途インストール不要
 *   - useragent を一般ブラウザのUAに設定してElectronによるブロックを回避
 *
 * 制限:
 *   - Widevine L1（ハードウェアバインド）は再生不可
 *   - 一部サービスはElectronのWebViewを明示的にブロックする場合がある
 *   - 動画の再生時刻をアノテーションストアと同期するには、
 *     対象サイトが標準HTML5 VideoElementを使用している必要がある
 */
import { useRef, useState, useCallback, useEffect } from 'react'
import { Globe, ArrowLeft, ArrowRight, RotateCcw, ExternalLink, AlertCircle, MonitorPlay } from 'lucide-react'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useTranslation } from 'react-i18next'

const BROWSER_UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'

interface WebViewPlayerProps {
  /** 初期表示URL */
  url: string
  /** サービス名（表示用） */
  siteName: string
}

export function WebViewPlayer({ url, siteName }: WebViewPlayerProps) {
  const { t } = useTranslation()

  const isLight = useIsLightMode()
  const webviewRef = useRef<HTMLElement>(null)
  const [currentUrl, setCurrentUrl] = useState(url)
  const [inputUrl, setInputUrl] = useState(url)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [canGoBack, setCanGoBack] = useState(false)
  const [canGoForward, setCanGoForward] = useState(false)
  const [pageTitle, setPageTitle] = useState(siteName)

  // webview の Electron イベントを購読
  useEffect(() => {
    const wv = webviewRef.current as any
    if (!wv) return

    const onDidStartLoading = () => {
      setIsLoading(true)
      setLoadError(null)
    }
    const onDidStopLoading = () => {
      setIsLoading(false)
      setCanGoBack(wv.canGoBack?.() ?? false)
      setCanGoForward(wv.canGoForward?.() ?? false)
    }
    const onDidFailLoad = (_e: any) => {
      // -3 は abort（リダイレクト中の正常キャンセル）なので無視
      if (_e.errorCode === -3) return
      setIsLoading(false)
      setLoadError(`読み込みエラー (${_e.errorCode}): ${_e.errorDescription}`)
    }
    const onPageTitleUpdated = (e: any) => {
      setPageTitle(e.title || siteName)
    }
    const onDidNavigate = (e: any) => {
      setCurrentUrl(e.url)
      setInputUrl(e.url)
    }
    const onDidNavigateInPage = (e: any) => {
      setCurrentUrl(e.url)
      setInputUrl(e.url)
      setCanGoBack(wv.canGoBack?.() ?? false)
      setCanGoForward(wv.canGoForward?.() ?? false)
    }

    wv.addEventListener('did-start-loading', onDidStartLoading)
    wv.addEventListener('did-stop-loading', onDidStopLoading)
    wv.addEventListener('did-fail-load', onDidFailLoad)
    wv.addEventListener('page-title-updated', onPageTitleUpdated)
    wv.addEventListener('did-navigate', onDidNavigate)
    wv.addEventListener('did-navigate-in-page', onDidNavigateInPage)

    return () => {
      wv.removeEventListener('did-start-loading', onDidStartLoading)
      wv.removeEventListener('did-stop-loading', onDidStopLoading)
      wv.removeEventListener('did-fail-load', onDidFailLoad)
      wv.removeEventListener('page-title-updated', onPageTitleUpdated)
      wv.removeEventListener('did-navigate', onDidNavigate)
      wv.removeEventListener('did-navigate-in-page', onDidNavigateInPage)
    }
  }, [siteName])

  const handleNavigate = useCallback(() => {
    const wv = webviewRef.current as any
    if (!wv) return
    const target = inputUrl.trim()
    if (!target) return
    // xss-through-dom 防止: URL パースで http(s) のみ許可し、文字列結合は行わない
    let parsed: URL
    try {
      parsed = new URL(target)
    } catch {
      return
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return
    wv.src = parsed.toString()
  }, [inputUrl])

  const handleBack = useCallback(() => {
    const wv = webviewRef.current as any
    wv?.goBack?.()
  }, [])

  const handleForward = useCallback(() => {
    const wv = webviewRef.current as any
    wv?.goForward?.()
  }, [])

  const handleReload = useCallback(() => {
    const wv = webviewRef.current as any
    wv?.reload?.()
  }, [])

  const handleOpenExternal = useCallback(() => {
    // Electron の shell.openExternal でシステムブラウザを起動
    // window.open は Electron では新規ウィンドウを開く場合がある
    window.open(currentUrl, '_blank')
  }, [currentUrl])

  // ── テーマ別スタイル定数 ──────────────────────────────────────────────────
  const outerBg     = isLight ? 'bg-white border border-gray-200'      : 'bg-gray-900 border border-gray-700'
  const navBarBg    = isLight ? 'bg-gray-100 border-b border-gray-200' : 'bg-gray-800 border-b border-gray-700'
  const titleBarBg  = isLight ? 'bg-gray-50 border-b border-gray-200'  : 'bg-gray-800/60 border-b border-gray-700/50'
  const btnHover    = isLight ? 'hover:bg-gray-200 text-gray-500 disabled:opacity-40' : 'hover:bg-gray-700 text-gray-400 disabled:opacity-30'
  const urlInputBg  = isLight ? 'bg-white border border-gray-300'      : 'bg-gray-700'
  const urlInputText = isLight ? 'text-gray-800'                        : 'text-gray-200'
  const titleText   = isLight ? 'text-gray-500'                         : 'text-gray-400'
  const errorBanner = isLight
    ? 'bg-red-50 border-b border-red-200 text-red-700'
    : 'bg-red-900/20 border-b border-red-700/40 text-red-300'

  return (
    <div
      className={`w-full flex flex-col rounded-lg overflow-hidden ${outerBg}`}
      style={{ aspectRatio: '16/9', minHeight: '200px' }}
    >
      {/* ── ナビゲーションバー ── */}
      <div className={`flex items-center gap-1 px-2 py-1.5 shrink-0 ${navBarBg}`}>
        {/* 戻る / 進む / 再読込 */}
        <button
          onClick={handleBack}
          disabled={!canGoBack}
          className={`p-1 rounded disabled:cursor-not-allowed ${btnHover}`}
          title={t('auto.WebViewPlayer.k2')}
        >
          <ArrowLeft size={14} />
        </button>
        <button
          onClick={handleForward}
          disabled={!canGoForward}
          className={`p-1 rounded disabled:cursor-not-allowed ${btnHover}`}
          title={t('auto.WebViewPlayer.k3')}
        >
          <ArrowRight size={14} />
        </button>
        <button
          onClick={handleReload}
          className={`p-1 rounded ${btnHover}`}
          title={t('auto.WebViewPlayer.k4')}
        >
          <RotateCcw size={14} className={isLoading ? 'animate-spin' : ''} />
        </button>

        {/* URL 入力バー */}
        <div className={`flex-1 flex items-center gap-1 rounded px-2 py-0.5 min-w-0 ${urlInputBg}`}>
          <Globe size={11} className={`shrink-0 ${titleText}`} />
          <input
            type="text"
            value={inputUrl}
            onChange={(e) => setInputUrl(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleNavigate() }}
            className={`flex-1 bg-transparent text-xs outline-none min-w-0 truncate ${urlInputText}`}
            aria-label="URL"
          />
        </div>

        {/* 外部ブラウザで開く */}
        <button
          onClick={handleOpenExternal}
          className={`p-1 rounded ${btnHover}`}
          title={t('auto.WebViewPlayer.k5')}
        >
          <ExternalLink size={14} />
        </button>
      </div>

      {/* ── ページタイトル（サービス名 + 読込インジケーター） ── */}
      <div className={`flex items-center gap-1.5 px-2 py-1 shrink-0 ${titleBarBg}`}>
        <MonitorPlay size={11} className="text-blue-400 shrink-0" />
        <span className={`text-[10px] truncate flex-1 ${titleText}`}>{pageTitle}</span>
        {isLoading && (
          <span className="text-[10px] text-blue-400 shrink-0 animate-pulse">{t('auto.WebViewPlayer.k1')}</span>
        )}
      </div>

      {/* ── エラー表示 ── */}
      {loadError && (
        <div className={`flex items-start gap-2 px-3 py-2 shrink-0 ${errorBanner}`}>
          <AlertCircle size={13} className="shrink-0 mt-0.5" />
          <span className="text-xs">{loadError}</span>
        </div>
      )}

      {/* ── WebView 本体 ── */}
      {/*
        partition="persist:streaming" でセッション（Cookie）を永続化
        useragent で Electron UA ブロックを回避
        disablewebsecurity="true" で CORS 制限を緩和
      */}
      <webview
        ref={webviewRef}
        src={url}
        partition="persist:streaming"
        useragent={BROWSER_UA}
        {...({ disablewebsecurity: 'true', allowpopups: 'true' } as Record<string, string>)}
        style={{ flex: 1, width: '100%' }}
      />
    </div>
  )
}
