/**
 * 配信URLダウンロードパネル
 *
 * YouTube / Twitter / Bilibili / ニコニコ動画 / 登録制配信サイト など、
 * Electron で直接再生できない配信URLを検出したときに表示する。
 *
 * yt-dlp でダウンロードし、完了後は localfile:// 経由でローカル再生に自動切替する。
 * ログイン必須サイトは「Cookieブラウザ」で使用ブラウザを選択すると、
 * そのブラウザのCookieを自動取得して認証を通過できる。
 *
 * 【ffmpegについて】
 * ffmpegが未インストールの場合、映像+音声マージが不要な
 * プリマージ済みストリームのみを使用するフォールバックモードで動作する。
 * 画質が制限される場合がある。
 */
import { useState, useEffect, useCallback } from 'react'
import { Download, AlertCircle, CheckCircle, Loader2, Film, Cookie, ChevronDown, WifiOff } from 'lucide-react'
import { apiGet, apiPost } from '@/api/client'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface StreamingDownloadPanelProps {
  /** 配信URL（表示 + ダウンロード元） */
  url: string
  /** 試合ID（ダウンロードAPI に使用） */
  matchId: string
  /** 検出されたサービス名（YouTube, Bilibili など） */
  siteName: string
  /** ダウンロード完了後に呼ばれるコールバック（match データ再取得を期待） */
  onDownloadComplete: () => void
}

type DLState = 'idle' | 'starting' | 'downloading' | 'processing' | 'complete' | 'error'

interface ProgressInfo {
  percent: string
  speed: string
  eta: string
}

interface Capabilities {
  yt_dlp: boolean
  ffmpeg: boolean
}

const QUALITY_OPTIONS = [
  { value: '360', label: '360p' },
  { value: '480', label: '480p' },
  { value: '720', label: '720p（推奨）' },
  { value: '1080', label: '1080p' },
  { value: 'best', label: '最高画質' },
]

const COOKIE_BROWSER_OPTIONS = [
  { value: '', label: 'なし（公開動画）' },
  { value: 'chrome', label: 'Chrome' },
  { value: 'edge', label: 'Edge' },
  { value: 'firefox', label: 'Firefox' },
  { value: 'brave', label: 'Brave' },
  { value: 'opera', label: 'Opera' },
  { value: 'vivaldi', label: 'Vivaldi' },
  { value: 'chromium', label: 'Chromium' },
]

export function StreamingDownloadPanel({
  url,
  matchId,
  siteName,
  onDownloadComplete,
}: StreamingDownloadPanelProps) {
  const isLight = useIsLightMode()
  const [quality, setQuality] = useState('720')
  const [cookieBrowser, setCookieBrowser] = useState('')
  const [dlState, setDlState] = useState<DLState>('idle')
  const [jobId, setJobId] = useState<string | null>(null)
  const [progress, setProgress] = useState<ProgressInfo>({ percent: '0%', speed: '', eta: '' })
  const [errorMsg, setErrorMsg] = useState('')
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)

  // ── システム機能確認（ffmpeg / yt-dlp 可用性） ────────────────────────────
  useEffect(() => {
    apiGet<{ success: boolean; data: Capabilities }>('/system/capabilities')
      .then((res) => setCapabilities(res.data))
      .catch(() => {
        // 取得失敗時はデフォルトとして両方 true 扱い（旧バックエンド互換）
        setCapabilities({ yt_dlp: true, ffmpeg: true })
      })
  }, [])

  // ── ダウンロード進捗ポーリング ──────────────────────────────────────────────
  useEffect(() => {
    if (!jobId || (dlState !== 'downloading' && dlState !== 'processing' && dlState !== 'starting')) return

    const poll = setInterval(async () => {
      try {
        const res = await apiGet<{
          success: boolean
          data: {
            status: string
            percent?: string
            speed?: string
            eta?: string
            error?: string
          }
        }>(`/matches/${matchId}/download/status`, { job_id: jobId })

        const d = res.data
        switch (d.status) {
          case 'complete':
            clearInterval(poll)
            setDlState('complete')
            setTimeout(onDownloadComplete, 800)
            break
          case 'error':
            clearInterval(poll)
            setDlState('error')
            setErrorMsg(d.error ?? '不明なエラー')
            break
          case 'downloading':
            setDlState('downloading')
            setProgress({
              percent: d.percent ?? '0%',
              speed: d.speed ?? '',
              eta: d.eta ?? '',
            })
            break
          case 'processing':
            setDlState('processing')
            break
          // pending / unknown は次のポーリングまで待機
        }
      } catch {
        // ネットワークエラーはスキップ
      }
    }, 1500)

    return () => clearInterval(poll)
  }, [jobId, dlState, matchId, onDownloadComplete])

  // ── ダウンロード開始 ────────────────────────────────────────────────────────
  const handleDownload = useCallback(async () => {
    setDlState('starting')
    setErrorMsg('')
    try {
      const res = await apiPost<{ success: boolean; data: { job_id: string } }>(
        `/matches/${matchId}/download`,
        { quality, cookie_browser: cookieBrowser }
      )
      setJobId(res.data.job_id)
      setDlState('downloading')
    } catch (err: any) {
      setDlState('error')
      setErrorMsg(err?.message ?? 'ダウンロード開始に失敗しました')
    }
  }, [matchId, quality, cookieBrowser])

  // ── リセット ────────────────────────────────────────────────────────────────
  const handleRetry = useCallback(() => {
    setDlState('idle')
    setJobId(null)
    setProgress({ percent: '0%', speed: '', eta: '' })
    setErrorMsg('')
  }, [])

  const isActive = dlState === 'starting' || dlState === 'downloading' || dlState === 'processing'
  const percentNum = Math.max(0, Math.min(100, parseFloat(progress.percent) || 0))
  const showCookieHint = !!cookieBrowser
  const ffmpegMissing = capabilities !== null && !capabilities.ffmpeg

  // ── テーマ別スタイル定数 ────────────────────────────────────────────────────
  const outerBg    = isLight ? 'bg-white border border-gray-200 shadow-sm' : 'bg-gray-800'
  const urlBoxBg   = isLight ? 'bg-gray-100' : 'bg-gray-900/60'
  const urlColor   = isLight ? '#0f172a' : '#ffffff'

  const bannerWarn = isLight
    ? 'text-orange-700 bg-orange-50 border border-orange-200'
    : 'text-orange-300 bg-orange-900/20 border border-orange-700/40'
  const bannerInfo = isLight
    ? 'text-yellow-800 bg-yellow-50 border border-yellow-200'
    : 'text-yellow-300 bg-yellow-900/20 border border-yellow-700/40'
  const bannerSuccess = isLight
    ? 'text-green-700 bg-green-50 border border-green-200'
    : 'text-green-400 bg-green-900/20 border border-green-700/40'
  const bannerError = isLight
    ? 'text-red-700 bg-red-50 border border-red-200'
    : 'text-red-300 bg-red-900/20 border border-red-700/40'
  const bannerBlue = isLight
    ? 'text-blue-800 bg-blue-50 border border-blue-200'
    : 'text-blue-300 bg-blue-900/20 border border-blue-700/40'

  const labelColor    = isLight ? 'text-gray-600' : 'text-gray-400'
  const muteColor     = isLight ? 'text-gray-500' : 'text-gray-500'
  const progressTrack = isLight ? 'bg-gray-200' : 'bg-gray-700'
  const siteColor     = isLight ? 'text-gray-900' : 'text-white'
  const retryColor    = isLight ? 'text-gray-500 hover:text-gray-800' : 'text-gray-400 hover:text-white'

  return (
    <div
      className={`flex flex-col gap-3 rounded-lg overflow-hidden ${outerBg}`}
      style={{ aspectRatio: '16/9', justifyContent: 'center', padding: '20px 24px' }}
    >
      {/* ── サービス名 + URL ── */}
      <div className="flex items-center gap-2 flex-wrap">
        <Film size={16} className="text-blue-400 shrink-0" />
        <span className={`text-sm font-semibold ${siteColor}`}>{siteName}</span>
        <span className={`text-xs ${muteColor}`}>配信URL</span>
      </div>

      <div
        className={`text-xs font-mono rounded px-2 py-1.5 truncate ${urlBoxBg}`}
        style={{ color: urlColor }}
      >
        {url}
      </div>

      {/* ── ffmpeg 未インストール警告 ── */}
      {ffmpegMissing && dlState === 'idle' && (
        <div className={`flex items-start gap-2 text-xs rounded p-2 ${bannerWarn}`}>
          <WifiOff size={13} className="shrink-0 mt-0.5" />
          <span>
            <strong>ffmpegが未インストール</strong> のため、画質が制限される場合があります。
            高画質が必要な場合は <code className={`px-1 rounded ${isLight ? 'bg-gray-200' : 'bg-gray-700'}`}>winget install ffmpeg</code> でインストール後アプリを再起動してください。
          </span>
        </div>
      )}

      {/* ── 説明バナー ── */}
      <div className={`flex items-start gap-2 text-xs rounded p-2 ${bannerInfo}`}>
        <AlertCircle size={13} className="shrink-0 mt-0.5" />
        <span>
          配信URLはElectronで直接再生できません。yt-dlpでダウンロードしてから再生します。
          ログイン必須サイトは「Cookieブラウザ」を選択してください。
        </span>
      </div>

      {/* ── 完了 ── */}
      {dlState === 'complete' && (
        <div className={`flex items-center gap-2 text-sm rounded p-3 ${bannerSuccess}`}>
          <CheckCircle size={16} />
          <span>ダウンロード完了！再生を開始します...</span>
        </div>
      )}

      {/* ── エラー ── */}
      {dlState === 'error' && (
        <div className="flex flex-col gap-2">
          <div className={`flex items-start gap-2 text-xs rounded p-2 ${bannerError}`}>
            <AlertCircle size={13} className="shrink-0 mt-0.5" />
            <span className="whitespace-pre-wrap break-all">{errorMsg}</span>
          </div>
          <button
            onClick={handleRetry}
            className={`text-xs underline text-left ${retryColor}`}
          >
            やり直す
          </button>
        </div>
      )}

      {/* ── 進捗バー（ダウンロード中） ── */}
      {isActive && (
        <div className="space-y-1.5">
          <div className={`flex items-center justify-between text-xs ${labelColor}`}>
            <div className="flex items-center gap-1.5">
              <Loader2 size={12} className="animate-spin text-blue-400" />
              <span>
                {dlState === 'starting'
                  ? '開始中...'
                  : dlState === 'processing'
                  ? 'マージ中...'
                  : progress.percent}
              </span>
            </div>
            <div className={`flex gap-3 ${muteColor}`}>
              {progress.speed && <span>{progress.speed}</span>}
              {progress.eta && dlState === 'downloading' && <span>残り {progress.eta}</span>}
            </div>
          </div>
          <div className={`h-2 rounded-full overflow-hidden ${progressTrack}`}>
            <div
              className={`h-full rounded-full transition-all duration-700 ${
                dlState === 'processing'
                  ? 'bg-yellow-500 w-full animate-pulse'
                  : dlState === 'starting'
                  ? 'bg-blue-500 w-[3%]'
                  : 'bg-blue-500'
              }`}
              style={dlState === 'downloading' ? { width: `${percentNum}%` } : undefined}
            />
          </div>
          {showCookieHint && (
            <p className={`text-xs ${muteColor}`}>
              🍪 {COOKIE_BROWSER_OPTIONS.find(o => o.value === cookieBrowser)?.label ?? cookieBrowser} のCookieを使用中
            </p>
          )}
        </div>
      )}

      {/* ── 品質 + Cookie + ダウンロードボタン（idle / error 時） ── */}
      {(dlState === 'idle' || dlState === 'error') && (
        <div className="flex flex-col gap-2">
          {/* 1行目: 品質 + Cookie ブラウザ */}
          <div className="flex items-center gap-2">
            {/* 品質選択 */}
            <div className="flex items-center gap-1 min-w-0">
              <label className={`text-xs shrink-0 ${labelColor}`}>画質</label>
              <select
                value={quality}
                onChange={(e) => setQuality(e.target.value)}
                className={`border text-xs rounded px-1.5 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                  isLight
                    ? 'bg-white border-gray-300 text-gray-800'
                    : 'bg-gray-700 border-gray-600 text-gray-200'
                }`}
              >
                {QUALITY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}{ffmpegMissing && opt.value !== '360' && opt.value !== '480' ? ' *' : ''}
                  </option>
                ))}
              </select>
              {ffmpegMissing && (
                <span className="text-[10px] text-orange-400" title="ffmpeg未インストールのため画質制限あり">*制限あり</span>
              )}
            </div>

            {/* Cookie ブラウザ選択 */}
            <div className="flex items-center gap-1 flex-1 min-w-0">
              <Cookie size={12} className={`shrink-0 ${labelColor}`} />
              <label className={`text-xs shrink-0 ${labelColor}`}>Cookie</label>
              <div className="relative flex-1 min-w-0">
                <select
                  value={cookieBrowser}
                  onChange={(e) => setCookieBrowser(e.target.value)}
                  className={`w-full border text-xs rounded px-1.5 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500 appearance-none pr-5 ${
                    isLight
                      ? 'bg-white border-gray-300 text-gray-800'
                      : 'bg-gray-700 border-gray-600 text-gray-200'
                  }`}
                >
                  {COOKIE_BROWSER_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <ChevronDown size={10} className={`absolute right-1.5 top-1/2 -translate-y-1/2 pointer-events-none ${labelColor}`} />
              </div>
            </div>
          </div>

          {/* Cookie 使用時の注意 */}
          {cookieBrowser && (
            <div className={`text-xs rounded px-2 py-1.5 space-y-0.5 ${bannerBlue}`}>
              <div><strong>{COOKIE_BROWSER_OPTIONS.find(o => o.value === cookieBrowser)?.label}</strong> のCookieをディスクから直接読み取ります。</div>
              <div className={isLight ? 'text-blue-600' : 'text-blue-400'}>ブラウザの起動は不要です。事前にそのブラウザでサイトへログインしておくだけでOKです。</div>
              <div className={`font-medium ${isLight ? 'text-orange-600' : 'text-orange-300'}`}>注意: ダウンロード前にそのブラウザをすべて閉じてください。起動中はDBがロックされCookieが読めません（Edge・Chromeは特に注意）。</div>
            </div>
          )}

          {/* ダウンロードボタン */}
          <button
            onClick={handleDownload}
            className="flex items-center justify-center gap-2 w-full py-2 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white rounded text-sm font-medium transition-colors"
          >
            <Download size={15} />
            ダウンロードして再生
            {ffmpegMissing && <span className="text-xs text-blue-300 ml-1">（低画質モード）</span>}
          </button>
        </div>
      )}
    </div>
  )
}
