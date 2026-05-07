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
import { Globe, ArrowLeft, ArrowRight, RotateCcw, ExternalLink, AlertCircle, MonitorPlay, Circle, Square } from 'lucide-react'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useTranslation } from 'react-i18next'
import { apiPost, apiGet } from '@/api/client'

// session storage の JWT を取得 (api/client 内部の TOKEN_KEY と一致)
function getStoredAuthToken(): string {
  try {
    return sessionStorage.getItem('shuttlescope_token') ?? ''
  } catch {
    return ''
  }
}

const BROWSER_UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'

type RecordState = 'idle' | 'starting' | 'recording' | 'stopping' | 'processing' | 'complete' | 'error'

interface WebViewPlayerProps {
  /** 初期表示URL */
  url: string
  /** サービス名（表示用） */
  siteName: string
  /** 紐付け試合 ID。指定するとアーカイブ完了時に Match.video_local_path が自動更新される */
  matchId?: number | null
  /** 録画完了時に呼ばれる (match データ再取得用) */
  onRecordingComplete?: () => void
}

export function WebViewPlayer({ url, siteName, matchId, onRecordingComplete }: WebViewPlayerProps) {
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

  // ── 画面キャプチャ録画 (会員限定 DRM 配信向け) ──
  // ライセンスされた視聴の OS-level ピクセル録画。yt-dlp が DRM 検知で blocked になる
  // サイトでも、ユーザがログイン状態で視聴できれば録れる。CDM bypass はしない。
  // Electron 限定機能 (window.shuttlescope?.screenCaptureStart が必要)。
  const [recordState, setRecordState] = useState<RecordState>('idle')
  const [recordError, setRecordError] = useState<string>('')
  const [recordJobId, setRecordJobId] = useState<string | null>(null)
  const [recordElapsedMs, setRecordElapsedMs] = useState<number>(0)
  const recordStartedAtRef = useRef<number>(0)

  // Electron API 利用可否
  const electronApi = (typeof window !== 'undefined') ? (window as any).shuttlescope : undefined
  const screenCaptureAvailable = !!electronApi?.screenCaptureStart && !!electronApi?.screenCaptureStop

  // 録画中の経過秒タイマー
  useEffect(() => {
    if (recordState !== 'recording') return
    const id = window.setInterval(() => {
      setRecordElapsedMs(Date.now() - recordStartedAtRef.current)
    }, 1000)
    return () => window.clearInterval(id)
  }, [recordState])

  // ジョブステータスポーリング (stop 後の processing → complete を追跡)
  useEffect(() => {
    if (!recordJobId || (recordState !== 'stopping' && recordState !== 'processing')) return
    const id = window.setInterval(async () => {
      try {
        const res = await apiGet<{ job_id: string; status: string; method: string; out_path: string; error?: string }>(
          `/youtube_live/${recordJobId}/status`,
        )
        if (res.status === 'complete' || res.status === 'archived') {
          window.clearInterval(id)
          setRecordState('complete')
          setTimeout(() => onRecordingComplete?.(), 600)
        } else if (res.status === 'error' || res.status === 'failed') {
          window.clearInterval(id)
          setRecordState('error')
          setRecordError(res.error ?? '録画失敗')
        } else if (res.status === 'remuxing' || res.status === 'archiving') {
          setRecordState('processing')
        }
      } catch {
        // ネットワークエラーは次回ポーリングまで待機
      }
    }, 2000)
    return () => window.clearInterval(id)
  }, [recordJobId, recordState, onRecordingComplete])

  const handleRecordStart = useCallback(async () => {
    if (!screenCaptureAvailable) {
      setRecordError('Electron アプリでのみ画面録画できます (Web 版では非対応)')
      setRecordState('error')
      return
    }
    setRecordError('')
    setRecordState('starting')
    try {
      // 1. backend にジョブを作成 (HLS プローブが失敗 → DRM フォールバック前提で
      //    method=drm_required を強制したいが、現状の API は probe してから
      //    自動判定する。会員限定サイトは HLS プローブが通らないので
      //    自然に drm_required になる)
      const startResp = await apiPost<{ job_id: string; method: string; status: string; error?: string }>(
        '/youtube_live/start',
        {
          url: currentUrl,
          quality: '720p',
          match_id: matchId ?? null,
        },
      )
      if (startResp.method === 'hls') {
        // HLS で取得できた場合 backend が ffmpeg で勝手に録る (Electron 不要)
        setRecordState('recording')
        setRecordJobId(startResp.job_id)
        recordStartedAtRef.current = Date.now()
        return
      }
      if (startResp.method !== 'drm_required') {
        throw new Error(startResp.error ?? `予期しないメソッド: ${startResp.method}`)
      }

      // 2. Electron 側で screen capture 開始
      const token = getStoredAuthToken()
      await electronApi.screenCaptureStart({
        url: currentUrl,
        jobId: startResp.job_id,
        token,
        matchId: matchId ?? null,
      })
      setRecordJobId(startResp.job_id)
      recordStartedAtRef.current = Date.now()
      setRecordState('recording')
    } catch (err: any) {
      setRecordState('error')
      setRecordError(err?.message ?? String(err))
    }
  }, [currentUrl, matchId, electronApi, screenCaptureAvailable])

  const handleRecordStop = useCallback(async () => {
    if (!recordJobId) return
    setRecordState('stopping')
    try {
      // Electron 録画停止 (HLS の場合は backend が独自に停止する)
      if (electronApi?.screenCaptureStop) {
        try { await electronApi.screenCaptureStop() } catch { /* ignore */ }
      }
      // Backend に stop シグナル → remux + archive 開始
      await apiPost(`/youtube_live/${recordJobId}/stop`, {})
      // status はポーリングで監視
    } catch (err: any) {
      setRecordState('error')
      setRecordError(err?.message ?? String(err))
    }
  }, [recordJobId, electronApi])

  const formatElapsed = (ms: number): string => {
    const s = Math.floor(ms / 1000)
    const mm = Math.floor(s / 60).toString().padStart(2, '0')
    const ss = (s % 60).toString().padStart(2, '0')
    return `${mm}:${ss}`
  }

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

        {/* 画面録画ボタン (Electron + 視聴中の DRM 配信用) */}
        {screenCaptureAvailable && (
          recordState === 'recording' || recordState === 'starting' ? (
            <button
              onClick={handleRecordStop}
              disabled={recordState === 'starting'}
              className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${
                isLight ? 'bg-red-100 text-red-700 hover:bg-red-200' : 'bg-red-900/40 text-red-300 hover:bg-red-800/60'
              }`}
              title="画面録画を停止"
            >
              <Square size={10} className="fill-current" />
              <span className="num-cell">{formatElapsed(recordElapsedMs)}</span>
            </button>
          ) : recordState === 'stopping' || recordState === 'processing' ? (
            <span className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${
              isLight ? 'bg-yellow-100 text-yellow-700' : 'bg-yellow-900/40 text-yellow-300'
            }`}>
              <RotateCcw size={10} className="animate-spin" />
              {recordState === 'stopping' ? '停止中…' : '保存中…'}
            </span>
          ) : recordState === 'complete' ? (
            <span className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${
              isLight ? 'bg-green-100 text-green-700' : 'bg-green-900/40 text-green-300'
            }`}>
              ✓ 保存済
            </span>
          ) : (
            <button
              onClick={handleRecordStart}
              className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${
                isLight ? 'bg-red-50 text-red-600 hover:bg-red-100 border border-red-200' : 'bg-red-900/20 text-red-400 hover:bg-red-900/40 border border-red-800/40'
              }`}
              title="この画面を録画開始 (会員限定 DRM 配信もライセンス済なら録画可能)"
            >
              <Circle size={10} className="fill-current" />
              録画
            </button>
          )
        )}

        {/* 外部ブラウザで開く */}
        <button
          onClick={handleOpenExternal}
          className={`p-1 rounded ${btnHover}`}
          title={t('auto.WebViewPlayer.k5')}
        >
          <ExternalLink size={14} />
        </button>
      </div>

      {/* 録画エラー表示 */}
      {recordState === 'error' && recordError && (
        <div className={`flex items-start gap-2 px-3 py-1.5 shrink-0 text-xs ${errorBanner}`}>
          <AlertCircle size={12} className="shrink-0 mt-0.5" />
          <span className="flex-1 break-words">録画エラー: {recordError}</span>
          <button
            onClick={() => { setRecordState('idle'); setRecordError(''); setRecordJobId(null) }}
            className="text-xs underline shrink-0"
          >
            閉じる
          </button>
        </div>
      )}

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
